from __future__ import annotations

from pathlib import Path

import pytest
import tomlkit

import utterplan.batch as batch_module
from utterplan import CompileRequest, FlowPlan, PlannerConfig, compile_to_files
from utterplan.exceptions import PlanFormatError


def _load_plan(path: Path) -> FlowPlan:
    return FlowPlan.from_toml(path.read_text(encoding="utf-8"))


def _requests(tmp_path: Path, *, count: int, invalid_index: int | None = None):
    requests = []
    for index in range(1, count + 1):
        source = "Hello.\n\n.\n\nWorld." if index == invalid_index else f"Document {index}."
        requests.append(
            CompileRequest(
                id=f"chapter-{index:02d}",
                source=source,
                output=tmp_path / "plans" / f"chapter-{index:02d}.utterplan.toml",
                input_format="plain",
                source_label=f"chapters/chapter-{index:02d}.txt",
            )
        )
    return requests


def test_item_three_failure_preserves_successes_and_continues_through_seventeen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = _requests(tmp_path, count=17, invalid_index=3)
    report_path = tmp_path / "plans" / "compile-report.toml"
    report_snapshots: list[dict[str, object]] = []
    real_write = batch_module.atomic_write_text

    def track_report(path: str | Path, value: str, *, create_parent: bool = False) -> None:
        if Path(path) == report_path:
            report_snapshots.append(dict(tomlkit.parse(value)))
        real_write(path, value, create_parent=create_parent)

    monkeypatch.setattr(batch_module, "atomic_write_text", track_report)
    outcomes = list(
        compile_to_files(
            requests,
            config=PlannerConfig(
                language="en-US", text_preparation="identity", renderability_mode="strict"
            ),
            report_path=report_path,
        )
    )

    assert len(outcomes) == 17
    assert [item.index for item in outcomes] == list(range(1, 18))
    assert [item.status for item in outcomes].count("written") == 16
    assert outcomes[2].status == "failed"
    assert outcomes[2].stage == "renderability"
    assert outcomes[2].error_code == "plan.not_renderable"
    assert outcomes[2].line == 3
    assert outcomes[2].error_message is not None
    assert "chapters/chapter-03.txt:3:1" in outcomes[2].error_message
    assert all(not hasattr(item, "plan") for item in outcomes)

    for index, request in enumerate(requests, start=1):
        if index == 3:
            assert not request.output.exists()
        else:
            assert request.output.exists()
            assert _load_plan(request.output).flow

    report = dict(tomlkit.parse(report_path.read_text(encoding="utf-8")))
    assert report["format"] == "utterplan-compile-report"
    assert report["version"] == 1
    assert report["requested"] == 17
    assert report["written"] == 16
    assert report["failed"] == 1
    assert report["skipped"] == 0
    assert report["complete"] is True
    items = report["item"]
    assert isinstance(items, list)
    assert len(items) == 17
    third = items[2]
    assert isinstance(third, dict)
    assert third["stage"] == "renderability"
    assert third["code"] == "plan.not_renderable"
    assert third["line"] == 3

    assert len(report_snapshots) == 19  # initial, each item, and final complete state
    assert report_snapshots[0]["complete"] is False
    assert report_snapshots[0]["item"] == []
    for expected_count, snapshot in enumerate(report_snapshots[1:18], start=1):
        items = snapshot["item"]
        assert isinstance(items, list)
        assert len(items) == expected_count
    assert all(snapshot["complete"] is False for snapshot in report_snapshots[1:18])
    assert report_snapshots[-1]["complete"] is True
    with pytest.raises(PlanFormatError):
        _load_plan(report_path)


def test_each_success_is_written_before_the_next_request_compiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = _requests(tmp_path, count=2)
    real_compile = batch_module.compile_document

    def observe_next_source(source: str, **kwargs):
        if source == requests[1].source:
            assert requests[0].output.exists()
        return real_compile(source, **kwargs)

    monkeypatch.setattr(batch_module, "compile_document", observe_next_source)
    outcomes = list(
        compile_to_files(
            requests,
            config=PlannerConfig(language="en-US", text_preparation="identity"),
        )
    )
    assert [item.status for item in outcomes] == ["written", "written"]


def test_fail_fast_marks_later_requests_skipped_without_processing(tmp_path: Path) -> None:
    requests = _requests(tmp_path, count=5, invalid_index=2)
    outcomes = list(
        compile_to_files(
            requests,
            config=PlannerConfig(
                language="en-US", text_preparation="identity", renderability_mode="strict"
            ),
            fail_fast=True,
        )
    )

    assert [item.status for item in outcomes] == [
        "written",
        "failed",
        "skipped",
        "skipped",
        "skipped",
    ]
    assert outcomes[1].error_code == "plan.not_renderable"
    assert all(not request.output.exists() for request in requests[1:])
    assert requests[0].output.exists()


def test_existing_output_is_protected_unless_force_is_explicit(tmp_path: Path) -> None:
    request = _requests(tmp_path, count=1)[0]
    request.output.parent.mkdir(parents=True)
    request.output.write_text("keep me", encoding="utf-8")
    config = PlannerConfig(language="en-US", text_preparation="identity")

    protected = list(compile_to_files([request], config=config))[0]
    assert protected.status == "failed"
    assert protected.error_code == "output.exists"
    assert request.output.read_text(encoding="utf-8") == "keep me"

    forced = list(compile_to_files([request], config=config, force=True))[0]
    assert forced.status == "written"
    assert _load_plan(request.output).plan_id == forced.plan_id


def test_target_write_failure_is_reported_and_later_requests_continue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = _requests(tmp_path, count=2)
    real_write = batch_module.atomic_write_text

    def fail_first(path: str | Path, value: str, *, create_parent: bool = False) -> None:
        if Path(path) == requests[0].output:
            raise OSError("simulated disk failure")
        real_write(path, value, create_parent=create_parent)

    monkeypatch.setattr(batch_module, "atomic_write_text", fail_first)
    outcomes = list(
        compile_to_files(
            requests,
            config=PlannerConfig(language="en-US", text_preparation="identity"),
        )
    )

    assert [item.status for item in outcomes] == ["failed", "written"]
    assert outcomes[0].stage == "write"
    assert outcomes[0].error_code == "output.write_failed"
    assert outcomes[0].error_message is not None
    assert "simulated disk failure" in outcomes[0].error_message
    assert not requests[0].output.exists()
    assert requests[1].output.exists()


def test_path_backed_read_failure_is_an_item_failure_and_continues(tmp_path: Path) -> None:
    source = tmp_path / "readable.txt"
    source.write_text("Read this.", encoding="utf-8")
    requests = [
        CompileRequest(
            id="first",
            source=source,
            output=tmp_path / "first.utterplan.toml",
            input_format="plain",
        ),
        CompileRequest(
            id="missing",
            source=tmp_path / "missing.txt",
            output=tmp_path / "missing.utterplan.toml",
            input_format="plain",
        ),
        CompileRequest(
            id="last",
            source=source,
            output=tmp_path / "last.utterplan.toml",
            input_format="plain",
        ),
    ]

    outcomes = list(
        compile_to_files(
            requests,
            config=PlannerConfig(language="en-US", text_preparation="identity"),
        )
    )

    assert [item.status for item in outcomes] == ["written", "failed", "written"]
    assert outcomes[1].stage == "read"
    assert outcomes[1].error_code == "input.read_failed"
    assert outcomes[1].source_label.endswith("missing.txt")
    assert _load_plan(requests[0].output).flow
    assert not requests[1].output.exists()
    assert _load_plan(requests[2].output).flow


def test_unexpected_programming_errors_are_not_converted_to_item_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _requests(tmp_path, count=1)[0]

    def broken_compile(*_args, **_kwargs):
        raise RuntimeError("programming error")

    monkeypatch.setattr(batch_module, "compile_document", broken_compile)
    with pytest.raises(RuntimeError, match="programming error"):
        list(
            compile_to_files(
                [request],
                config=PlannerConfig(language="en-US", text_preparation="identity"),
            )
        )


def test_interrupted_iteration_leaves_an_incomplete_atomic_report(tmp_path: Path) -> None:
    requests = iter(_requests(tmp_path, count=3))
    report_path = tmp_path / "compile-report.toml"
    outcomes = compile_to_files(
        requests,
        config=PlannerConfig(language="en-US", text_preparation="identity"),
        report_path=report_path,
    )

    first = next(outcomes)
    assert first.status == "written"
    outcomes.close()

    report = dict(tomlkit.parse(report_path.read_text(encoding="utf-8")))
    assert report["complete"] is False
    assert report["written"] == 1
    assert [item["id"] for item in report["item"]] == ["chapter-01"]
