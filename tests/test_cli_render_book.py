from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
import tomlkit
from renderplan import (
    PausePolicy,
    PlanningPolicy,
    RenderProfile,
    RoleProfile,
    load_renderplan_set,
)
from renderplan import codec as renderplan_codec

from utterplan import FlowPlan, FlowSegment, FlowUnit, TokenView
from utterplan.cli import build_parser, main


def _ssmd(text: str) -> str:
    return f'---\nssmd_version: "0.9"\nlanguage: en-US\n---\n{text}\n'


def _write_book(
    root: Path,
    numbers: tuple[int, ...],
    *,
    names: dict[int, str] | None = None,
    plans: tuple[int, ...] | None = None,
    utterplan_dir: Path | None = None,
) -> Path:
    entries: list[dict[str, object]] = []
    for number in numbers:
        relative = (names or {}).get(number, f"chapters/chapter-{number:04d}.ssmd.md")
        source = root / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(_ssmd(f"Book chapter {number}."), encoding="utf-8")
        entries.append(
            {
                "id": f"chapter-{number:04d}",
                "source_number": number,
                "path": relative,
                "title": f"Chapter {number}",
            }
        )
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "format": "ssmdconvert.book",
                "schema_version": 1,
                "ssmd_version": "0.9",
                "chapters": entries,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    selected_plan_dir = utterplan_dir or root / "utterplan"
    selected_plan_dir.mkdir(parents=True, exist_ok=True)
    for number in plans if plans is not None else numbers:
        text = f"Semantic chapter {number}."
        flowplan = FlowPlan(
            language="en-US",
            flow=(
                FlowUnit(
                    (
                        FlowSegment(
                            text,
                            "en-US",
                            tokens=(TokenView(0, len(text)),),
                            boundary_after=("sentence",),
                        ),
                    )
                ),
            ),
        )
        flowplan.save(selected_plan_dir / f"chapter-{number:04d}.utterplan.toml")
    return root


def _profile(path: Path, voice: str = "amy") -> RenderProfile:
    profile = RenderProfile(
        roles={
            "narrator": RoleProfile(language="en-US", binding={"engine": "fixture", "voice": voice})
        },
        default_role="narrator",
        planning=PlanningPolicy(split="sentence", capacity_fallback=("token",)),
        pauses=PausePolicy(mode="manual", durations_ms={"sentence": 250}),
    )
    renderplan_codec.save_profile(profile, path)
    return renderplan_codec.load_profile(path)


def _render(
    root: Path,
    profile_path: Path,
    *options: str,
    input_path: Path | None = None,
) -> int:
    return main(
        [
            "render-book",
            str(input_path or root),
            *options,
            "--profile",
            str(profile_path),
        ]
    )


def _variant(root: Path, profile: RenderProfile, label: str = "narration") -> Path:
    profile_id = profile.profile_id or profile.computed_id()
    return root / "renderplan" / f"{label}--{profile_id.removeprefix('sha256:')[:12]}"


def _report(path: Path) -> dict[str, object]:
    return dict(tomlkit.parse(path.read_text(encoding="utf-8")).unwrap())


def test_render_book_parser_defaults_and_required_profile() -> None:
    args = build_parser().parse_args(
        [
            "render-book",
            "book.ssmdbook",
            "--chapters",
            "1,3-5",
            "--profile",
            "narration.renderprofile.toml",
        ]
    )
    assert args.command == "render-book"
    assert args.chapters == "1,3-5"
    assert args.variant is None
    assert args.output_root is None
    assert args.utterplan_dir is None
    assert args.report is None
    assert args.force is False
    assert args.fail_fast is False
    with pytest.raises(SystemExit):
        build_parser().parse_args(["render-book", "book.ssmdbook"])


def test_render_book_success_matches_single_file_projection(tmp_path: Path, capsys) -> None:
    root = _write_book(tmp_path / "ordered.ssmdbook", (5, 7, 6))
    profile_path = root / "narration.renderprofile.toml"
    profile = _profile(profile_path)
    manifest_before = (root / "manifest.json").read_bytes()

    result = _render(root, profile_path, "--chapters", "5-7")
    captured = capsys.readouterr()
    variant = _variant(root, profile)
    set_path = variant / "renderplan-set.toml"
    report_path = variant / "render-report.toml"
    loaded_set = load_renderplan_set(set_path)

    assert result == 0
    assert "selected:   3" in captured.err
    assert [chapter.id for chapter in loaded_set.chapters] == [
        "chapter-0005",
        "chapter-0007",
        "chapter-0006",
    ]
    assert loaded_set.profile_id == profile.profile_id
    assert loaded_set.profile_fingerprint == profile.profile_id.removeprefix("sha256:")[:12]
    snapshot = renderplan_codec.load_profile(variant / "renderprofile.toml")
    assert snapshot.profile_id == loaded_set.profile_id
    for chapter in loaded_set.chapters:
        plan_path = variant / chapter.renderplan
        plan = renderplan_codec.load_plan(plan_path)
        assert plan.render_profile_id == loaded_set.profile_id
        assert (
            chapter.source_plan_id
            == FlowPlan.load(root / "utterplan" / f"{chapter.id}.utterplan.toml").plan_id
        )
        assert chapter.render_plan_id == plan.plan_id

    report = _report(report_path)
    assert report["format"] == "utterplan-render-report"
    assert report["complete"] is True
    assert report["requested"] == 3
    assert report["written"] == 3
    assert report["failed"] == 0
    assert len(report["item"]) == 3
    assert (root / "manifest.json").read_bytes() == manifest_before

    source_plan = root / "utterplan/chapter-0005.utterplan.toml"
    single_output = tmp_path / "chapter-0005.single.renderplan.toml"
    assert (
        main(
            [
                "render-plan",
                str(source_plan),
                "--profile",
                str(profile_path),
                "-o",
                str(single_output),
            ]
        )
        == 0
    )
    batch_plan = renderplan_codec.load_plan(variant / "chapter-0005.renderplan.toml")
    single_plan = renderplan_codec.load_plan(single_output)
    assert batch_plan == single_plan
    assert batch_plan.plan_id == single_plan.plan_id


def test_render_book_accumulates_successful_chapters_and_replaces_latest_report(
    tmp_path: Path, capsys
) -> None:
    root = _write_book(tmp_path / "incremental.ssmdbook", (5, 6, 7, 8))
    profile_path = root / "narration.renderprofile.toml"
    profile = _profile(profile_path)

    assert _render(root, profile_path, "--chapters", "5-6") == 0
    capsys.readouterr()
    variant = _variant(root, profile)
    first_plan_bytes = (variant / "chapter-0005.renderplan.toml").read_bytes()
    assert _render(root, profile_path, "--chapters", "7-8") == 0
    capsys.readouterr()

    collection = load_renderplan_set(variant / "renderplan-set.toml")
    assert [chapter.source_number for chapter in collection.chapters] == [5, 6, 7, 8]
    assert (variant / "chapter-0005.renderplan.toml").read_bytes() == first_plan_bytes
    report = _report(variant / "render-report.toml")
    assert report["requested"] == 2
    assert [item["source_number"] for item in report["item"]] == [7, 8]


def test_different_profile_id_creates_independent_variant(tmp_path: Path, capsys) -> None:
    root = _write_book(tmp_path / "voices.ssmdbook", (5,))
    amy_path = root / "amy.renderprofile.toml"
    joe_path = root / "joe.renderprofile.toml"
    amy = _profile(amy_path, "amy")
    joe = _profile(joe_path, "joe")

    assert _render(root, amy_path, "--chapters", "5") == 0
    capsys.readouterr()
    amy_variant = _variant(root, amy, "amy")
    amy_plan_bytes = (amy_variant / "chapter-0005.renderplan.toml").read_bytes()
    assert _render(root, joe_path, "--chapters", "5") == 0
    capsys.readouterr()
    joe_variant = _variant(root, joe, "joe")

    assert amy.profile_id != joe.profile_id
    assert amy_variant != joe_variant
    assert (amy_variant / "chapter-0005.renderplan.toml").read_bytes() == amy_plan_bytes
    assert load_renderplan_set(joe_variant / "renderplan-set.toml").profile_id == joe.profile_id
    assert (
        renderplan_codec.load_profile(joe_variant / "renderprofile.toml").profile_id
        == joe.profile_id
    )


@pytest.mark.parametrize(
    ("fail_fast", "expected_statuses", "expected_set"),
    [
        (False, ["written", "failed", "written"], ["chapter-0005", "chapter-0007"]),
        (True, ["written", "failed", "skipped"], ["chapter-0005"]),
    ],
)
def test_render_book_missing_plan_continues_or_skips(
    tmp_path: Path,
    capsys,
    fail_fast: bool,
    expected_statuses: list[str],
    expected_set: list[str],
) -> None:
    root = _write_book(tmp_path / f"partial-{fail_fast}.ssmdbook", (5, 6, 7), plans=(5, 7))
    profile_path = root / "narration.renderprofile.toml"
    profile = _profile(profile_path)
    options = ["--chapters", "5-7"]
    if fail_fast:
        options.extend(["--fail-fast", "--variant", "failfast"])
    result = _render(root, profile_path, *options)
    captured = capsys.readouterr()
    variant = _variant(root, profile, "failfast" if fail_fast else "narration")

    assert result == 1
    assert [
        item["status"] for item in _report(variant / "render-report.toml")["item"]
    ] == expected_statuses
    report = _report(variant / "render-report.toml")
    assert report["item"][1]["code"] == "input.missing"
    assert report["item"][1]["stage"] == "load"
    assert [
        chapter.id for chapter in load_renderplan_set(variant / "renderplan-set.toml").chapters
    ] == expected_set
    if not fail_fast:
        assert "RenderPlans are already saved" in captured.err


def test_render_book_force_replaces_only_after_success(tmp_path: Path, capsys) -> None:
    root = _write_book(tmp_path / "force.ssmdbook", (5,))
    profile_path = root / "narration.renderprofile.toml"
    profile = _profile(profile_path)
    assert _render(root, profile_path, "--chapters", "5") == 0
    capsys.readouterr()
    variant = _variant(root, profile)
    output = variant / "chapter-0005.renderplan.toml"
    before = output.read_bytes()
    previous = load_renderplan_set(variant / "renderplan-set.toml").chapters[0]

    changed_text = "Changed semantic chapter 5."
    changed = FlowPlan(
        language="en-US",
        flow=(FlowUnit((FlowSegment(changed_text, "en-US"),)),),
    )
    changed.save(root / "utterplan/chapter-0005.utterplan.toml")
    assert _render(root, profile_path, "--chapters", "5") == 1
    captured = capsys.readouterr()
    assert "output.exists" in captured.err
    assert output.read_bytes() == before
    assert load_renderplan_set(variant / "renderplan-set.toml").chapters[0] == previous

    assert _render(root, profile_path, "--chapters", "5", "--force") == 0
    capsys.readouterr()
    updated = load_renderplan_set(variant / "renderplan-set.toml").chapters[0]
    assert updated.source_plan_id != previous.source_plan_id
    assert updated.render_plan_id != previous.render_plan_id
    assert renderplan_codec.load_plan(output).speech[0].text == changed_text


def test_render_book_supports_custom_roots_and_sanitizes_variant_label(
    tmp_path: Path, capsys
) -> None:
    root = _write_book(tmp_path / "custom.ssmdbook", (5,))
    custom_plans = tmp_path / "generated-plans"
    _write_book(root, (5,), utterplan_dir=custom_plans)
    profile_path = root / "narration.renderprofile.toml"
    profile = _profile(profile_path)
    output_root = tmp_path / "build" / "renderplan"

    result = _render(
        root,
        profile_path,
        "--chapters",
        "5",
        "--utterplan-dir",
        str(custom_plans),
        "--output-root",
        str(output_root),
        "--variant",
        "../Book Audio/..",
        input_path=root / "chapters",
    )
    capsys.readouterr()
    variant = output_root / f"book-audio--{profile.profile_id.removeprefix('sha256:')[:12]}"
    assert result == 0
    assert (variant / "chapter-0005.renderplan.toml").is_file()
    expected_utterplan = Path(
        os.path.relpath(custom_plans / "chapter-0005.utterplan.toml", start=variant)
    ).as_posix()
    assert (
        load_renderplan_set(variant / "renderplan-set.toml").chapters[0].utterplan
        == expected_utterplan
    )
    assert not (tmp_path / "Book Audio").exists()


def test_invalid_profile_and_unsafe_paths_do_not_create_outputs(tmp_path: Path, capsys) -> None:
    root = _write_book(tmp_path / "unsafe.ssmdbook", (5,))
    invalid_profile = root / "invalid.renderprofile.toml"
    invalid_profile.write_text("not valid TOML", encoding="utf-8")
    assert _render(root, invalid_profile, "--chapters", "5") == 2
    capsys.readouterr()
    assert not (root / "renderplan").exists()

    profile_path = root / "narration.renderprofile.toml"
    _profile(profile_path)
    assert (
        _render(
            root,
            profile_path,
            "--chapters",
            "5",
            "--output-root",
            str(root / "chapters" / "generated"),
        )
        == 2
    )
    capsys.readouterr()
    assert not (root / "chapters/generated").exists()

    assert (
        _render(root, profile_path, "--chapters", "5", "--report", str(root / "manifest.json")) == 2
    )
    capsys.readouterr()
    assert not (root / "renderplan").exists()


def test_render_book_rejects_legacy_plan_before_collection_state_is_written(
    tmp_path: Path, capsys
) -> None:
    root = _write_book(tmp_path / "legacy.ssmdbook", (5,))
    profile_path = root / "narration.renderprofile.toml"
    _profile(profile_path)
    source_plan = root / "utterplan" / "chapter-0005.utterplan.toml"
    legacy_fixture = Path(__file__).parent / "schema_history/v5/canonical_consumer_contract.toml"
    shutil.copyfile(legacy_fixture, source_plan)

    assert _render(root, profile_path, "--chapters", "5") == 1
    assert "schema.version_unsupported" in capsys.readouterr().err
    assert not (root / "renderplan").exists()


def test_duplicate_source_basenames_are_rejected_before_output_creation(
    tmp_path: Path, capsys
) -> None:
    root = _write_book(
        tmp_path / "duplicates.ssmdbook",
        (5, 6),
        names={
            5: "chapters/part-a/chapter.ssmd.md",
            6: "chapters/part-b/chapter.ssmd.md",
        },
    )
    profile_path = root / "narration.renderprofile.toml"
    _profile(profile_path)

    assert _render(root, profile_path, "--chapters", "5-6") == 2
    assert "collide" in capsys.readouterr().err
    assert not (root / "renderplan").exists()


def test_existing_variant_corruption_and_nonempty_unindexed_directory_fail_closed(
    tmp_path: Path, capsys
) -> None:
    root = _write_book(tmp_path / "corrupt.ssmdbook", (5, 6))
    profile_path = root / "narration.renderprofile.toml"
    profile = _profile(profile_path)
    variant = _variant(root, profile)
    variant.mkdir(parents=True)
    (variant / "experiment.txt").write_text("unindexed", encoding="utf-8")

    assert _render(root, profile_path, "--chapters", "5", "--force") == 2
    assert "refusing to adopt" in capsys.readouterr().err
    assert not (variant / "renderplan-set.toml").exists()


def test_malformed_set_and_missing_snapshot_fail_closed_even_with_force(
    tmp_path: Path, capsys
) -> None:
    root = _write_book(tmp_path / "provenance.ssmdbook", (5, 6))
    profile_path = root / "narration.renderprofile.toml"
    profile = _profile(profile_path)
    assert _render(root, profile_path, "--chapters", "5") == 0
    capsys.readouterr()
    variant = _variant(root, profile)
    set_path = variant / "renderplan-set.toml"
    set_bytes = set_path.read_bytes()
    set_path.write_text("format = [", encoding="utf-8")

    assert _render(root, profile_path, "--chapters", "6", "--force") == 2
    assert "invalid existing renderplan-set.toml" in capsys.readouterr().err
    assert not (variant / "chapter-0006.renderplan.toml").exists()

    set_path.write_bytes(set_bytes)
    (variant / "renderprofile.toml").unlink()
    assert _render(root, profile_path, "--chapters", "6", "--force") == 2
    assert "snapshot is missing" in capsys.readouterr().err
    assert not (variant / "chapter-0006.renderplan.toml").exists()


def test_existing_set_and_snapshot_mismatches_are_not_bypassed_by_force(
    tmp_path: Path, capsys
) -> None:
    root = _write_book(tmp_path / "mismatch.ssmdbook", (5, 6))
    profile_a_path = root / "narration.renderprofile.toml"
    profile_b_path = root / "other.renderprofile.toml"
    profile_a = _profile(profile_a_path, "amy")
    profile_b = _profile(profile_b_path, "joe")
    assert _render(root, profile_a_path, "--chapters", "5", "--variant", "shared") == 0
    capsys.readouterr()
    variant_a = _variant(root, profile_a, "shared")
    variant_b = _variant(root, profile_b, "shared")
    shutil.copytree(variant_a, variant_b)

    assert _render(root, profile_b_path, "--chapters", "6", "--variant", "shared", "--force") == 2
    assert "does not match the active RenderProfile" in capsys.readouterr().err
    assert not (variant_b / "chapter-0006.renderplan.toml").exists()

    renderplan_codec.save_profile(profile_b, variant_a / "renderprofile.toml")
    assert _render(root, profile_a_path, "--chapters", "6", "--variant", "shared", "--force") == 2
    assert "snapshot identity" in capsys.readouterr().err
    assert not (variant_a / "chapter-0006.renderplan.toml").exists()
