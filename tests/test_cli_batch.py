from __future__ import annotations

from pathlib import Path

import pytest
import tomlkit

from utterplan import FlowPlan
from utterplan.cli import build_parser, main
from utterplan.exceptions import PlanFormatError


def _write(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _report(path: Path):
    return dict(tomlkit.parse(path.read_text(encoding="utf-8")))


def test_compile_many_uses_stable_names_and_writes_toml_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sources = [
        _write(
            tmp_path / "chapter-01.ssmd",
            '---\nssmd_version: "0.9"\nlanguage: en-US\n---\nFirst chapter.',
        ),
        _write(
            tmp_path / "chapter-02.ssmd.md",
            '---\nssmd_version: "0.9"\nlanguage: en-US\n---\nSecond chapter.',
        ),
        _write(
            tmp_path / "chapter-03.md",
            '---\nssmd_version: "0.9"\nlanguage: en-US\n---\nThird chapter.',
        ),
    ]
    output_dir = tmp_path / "plans"

    result = main(
        [
            "compile-many",
            *(str(source) for source in sources),
            "--output-dir",
            str(output_dir),
            "--text-preparation",
            "identity",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == ""
    assert "[1/3]" in captured.err and "[3/3]" in captured.err
    assert "requested: 3" in captured.err and "written:   3" in captured.err
    expected = (
        "chapter-01.utterplan.toml",
        "chapter-02.utterplan.toml",
        "chapter-03.utterplan.toml",
    )
    for name in expected:
        plan_path = output_dir / name
        assert FlowPlan.load(plan_path).flow
    report_path = output_dir / "compile-report.toml"
    report = _report(report_path)
    assert report["format"] == "utterplan-compile-report"
    assert report["requested"] == 3
    assert report["written"] == 3
    assert report["failed"] == 0
    assert report["complete"] is True
    with pytest.raises(PlanFormatError):
        FlowPlan.load(report_path)


def test_compile_many_continues_after_planning_and_source_read_failures(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _write(tmp_path / "first.txt", "First document.")
    broken = _write(tmp_path / "broken.txt", "€")
    missing = tmp_path / "missing.txt"
    last = _write(tmp_path / "last.txt", "Last document.")
    output_dir = tmp_path / "plans"

    result = main(
        [
            "compile-many",
            str(first),
            str(broken),
            str(missing),
            str(last),
            "--output-dir",
            str(output_dir),
            "--language",
            "en-US",
            "--input-format",
            "plain",
            "--text-preparation",
            "identity",
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "continuing with" in captured.err
    assert "this symbol has no declared spoken interpretation" in captured.err
    assert "intended spoken words" in captured.err
    assert str(missing) in captured.err
    assert "input.read_failed" in captured.err
    assert "written:   2" in captured.err
    assert "failed:    2" in captured.err
    assert (output_dir / "first.utterplan.toml").exists()
    assert not (output_dir / "broken.utterplan.toml").exists()
    assert not (output_dir / "missing.utterplan.toml").exists()
    assert (output_dir / "last.utterplan.toml").exists()
    report = _report(output_dir / "compile-report.toml")
    items = report["item"]
    assert [item["status"] for item in items] == ["written", "failed", "failed", "written"]
    assert items[1]["stage"] == "renderability"
    assert items[2]["stage"] == "read"


def test_compile_many_fail_fast_marks_remaining_inputs_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _write(tmp_path / "first.txt", "First document.")
    broken = _write(tmp_path / "broken.txt", "€")
    last = _write(tmp_path / "last.txt", "Last document.")
    output_dir = tmp_path / "plans"

    result = main(
        [
            "compile-many",
            str(first),
            str(broken),
            str(last),
            "--output-dir",
            str(output_dir),
            "--language",
            "en-US",
            "--input-format",
            "plain",
            "--text-preparation",
            "identity",
            "--fail-fast",
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "skipped:   1" in captured.err
    assert (output_dir / "first.utterplan.toml").exists()
    assert not (output_dir / "broken.utterplan.toml").exists()
    assert not (output_dir / "last.utterplan.toml").exists()
    report = _report(output_dir / "compile-report.toml")
    assert report["failed"] == 1
    assert report["skipped"] == 1
    assert report["complete"] is True


def test_compile_many_preflights_duplicate_outputs_before_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _write(tmp_path / "one" / "chapter.ssmd", "first")
    second = _write(tmp_path / "two" / "chapter.ssmd", "second")
    output_dir = tmp_path / "plans"

    result = main(["compile-many", str(first), str(second), "--output-dir", str(output_dir)])

    captured = capsys.readouterr()
    assert result == 2
    assert "map to the same output" in captured.err
    assert not output_dir.exists()


def test_compile_many_rejects_report_path_that_collides_with_plan_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _write(tmp_path / "chapter.txt", "A chapter.")
    output_dir = tmp_path / "plans"
    report_path = output_dir / "chapter.utterplan.toml"

    result = main(
        [
            "compile-many",
            str(source),
            "--output-dir",
            str(output_dir),
            "--report",
            str(report_path),
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "report path collides with plan output" in captured.err
    assert not output_dir.exists()


def test_compile_many_protects_existing_output_and_force_replaces_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _write(tmp_path / "chapter.txt", "Replacement chapter.")
    output_dir = tmp_path / "plans"
    output_dir.mkdir()
    destination = output_dir / "chapter.utterplan.toml"
    destination.write_text("keep this", encoding="utf-8")
    common = [
        "compile-many",
        str(source),
        "--output-dir",
        str(output_dir),
        "--language",
        "en-US",
        "--input-format",
        "plain",
        "--text-preparation",
        "identity",
    ]

    protected = main(common)
    protected_output = capsys.readouterr()
    assert protected == 1
    assert destination.read_text(encoding="utf-8") == "keep this"
    assert "output already exists" in protected_output.err

    forced = main([*common, "--force"])
    forced_output = capsys.readouterr()
    assert forced == 0
    assert "wrote" in forced_output.err
    assert (
        "".join(
            segment.text for unit in FlowPlan.load(destination).flow for segment in unit.segments
        )
        == "Replacement chapter."
    )


def test_compile_many_repair_and_strict_modes_preserve_unattachable_punctuation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _write(tmp_path / "chapter.txt", "Hello.\n\n.\n\nWorld.")
    repair_dir = tmp_path / "repair"
    repair_result = main(
        [
            "compile-many",
            str(source),
            "--output-dir",
            str(repair_dir),
            "--language",
            "en-US",
            "--input-format",
            "plain",
            "--text-preparation",
            "identity",
        ]
    )
    repair_output = capsys.readouterr()
    assert repair_result == 1
    assert "isolated punctuation became its own speech segment" in repair_output.err
    assert "Prepared fragment: '.'" in repair_output.err
    assert (
        "Automatic repair: safe; remove the isolated punctuation-only segment." in repair_output.err
    )
    assert not (repair_dir / "chapter.utterplan.toml").exists()

    strict_dir = tmp_path / "strict"
    strict_result = main(
        [
            "compile-many",
            str(source),
            "--output-dir",
            str(strict_dir),
            "--language",
            "en-US",
            "--input-format",
            "plain",
            "--text-preparation",
            "identity",
            "--renderability",
            "strict",
        ]
    )
    strict_output = capsys.readouterr()
    assert strict_result == 1
    assert "Automatic repair: safe;" in strict_output.err
    assert "Prepared fragment:" in strict_output.err
    assert not (strict_dir / "chapter.utterplan.toml").exists()


def test_compile_many_requires_language_when_no_source_language_exists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _write(tmp_path / "plain.txt", "A plain source.")
    output_dir = tmp_path / "plans"

    result = main(
        ["compile-many", str(source), "--output-dir", str(output_dir), "--input-format", "plain"]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "plain input requires --language" in captured.err
    assert not (output_dir / "plain.utterplan.toml").exists()


def test_compile_many_parser_defaults_to_repair_and_continue() -> None:
    args = build_parser().parse_args(["compile-many", "one.txt", "--output-dir", "plans"])
    assert args.renderability == "repair"
    assert args.fail_fast is False
