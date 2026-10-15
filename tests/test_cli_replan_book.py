from __future__ import annotations

import json
from pathlib import Path

import pytest
from renderplan import (
    PausePolicy,
    PlanningPolicy,
    PreflightCheck,
    PreflightReport,
    RenderProfile,
    ReplanRequest,
    RoleProfile,
    load_renderplan_set,
)
from renderplan import codec as renderplan_codec

from utterplan import FlowPlan, FlowSegment, FlowUnit, TokenView, render_book
from utterplan.cli import build_parser, main


def _write_workspace(root: Path, numbers: tuple[int, ...] = (5,)) -> Path:
    root.mkdir(parents=True)
    plans = root / "utterplan"
    plans.mkdir()
    chapters: list[dict[str, object]] = []
    for number in numbers:
        source = root / "chapters" / f"chapter-{number:04d}.ssmd.md"
        source.parent.mkdir(exist_ok=True)
        source.write_text(
            f'---\nssmd_version: "0.9"\nlanguage: en-US\n---\nChapter {number}.\n',
            encoding="utf-8",
        )
        chapters.append(
            {
                "id": f"chapter-{number:04d}",
                "source_number": number,
                "path": f"chapters/{source.name}",
                "title": f"Chapter {number}",
            }
        )
        text = f"chapter {number} has one two three four."
        words = ["chapter", str(number), "has", "one", "two", "three", "four."]
        tokens: list[TokenView] = []
        cursor = 0
        for word in words:
            start = text.index(word, cursor)
            end = start + len(word)
            tokens.append(TokenView(start, end))
            cursor = end
        FlowPlan(
            language="en-US",
            flow=(
                FlowUnit(
                    (
                        FlowSegment(
                            text, "en-US", tokens=tuple(tokens), boundary_after=("sentence",)
                        ),
                    )
                ),
            ),
        ).save(plans / f"chapter-{number:04d}.utterplan.toml")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "format": "ssmdconvert.book",
                "schema_version": 1,
                "ssmd_version": "0.9",
                "chapters": chapters,
            }
        ),
        encoding="utf-8",
    )
    return root


def _profile(path: Path) -> RenderProfile:
    profile = RenderProfile(
        roles={"narrator": RoleProfile(language="en-US", binding={"engine": "fixture"})},
        default_role="narrator",
        planning=PlanningPolicy(split="sentence", capacity_fallback=("token",)),
        pauses=PausePolicy(mode="manual", durations_ms={"sentence": 300}),
    )
    renderplan_codec.save_profile(profile, path)
    return renderplan_codec.load_profile(path)


def _prepared(
    tmp_path: Path,
    *,
    numbers: tuple[int, ...] = (5,),
    renderplan_root: Path | None = None,
    voicerender_root: Path | None = None,
) -> tuple[Path, str, Path, RenderProfile]:
    root = _write_workspace(tmp_path / "book.ssmdbook", numbers)
    profile_path = root / "narration.renderprofile.toml"
    profile = _profile(profile_path)
    rendered = render_book(
        root,
        profile=profile_path,
        output_root=renderplan_root,
    )
    active_voice_root = voicerender_root or root / "voicerender"
    for chapter in rendered.selected_chapter_ids:
        entry = next(
            item for item in load_renderplan_set(rendered.set_path).chapters if item.id == chapter
        )
        plan = renderplan_codec.load_plan(rendered.variant_dir / entry.renderplan)
        speech = plan.speech[0]
        segment_id = speech.segment_id or speech.computed_id()
        report = PreflightReport(
            render_plan_id=plan.plan_id or plan.computed_id(),
            source_plan_id=plan.source_plan_id,
            render_profile_id=profile.profile_id or profile.computed_id(),
            status="replan",
            checks=(
                PreflightCheck(
                    segment_number=speech.number,
                    segment_id=segment_id,
                    status="too_long",
                    metric="model_tokens",
                    measured=700,
                    maximum=400,
                    source="fixture-renderer",
                ),
            ),
            replan=(
                ReplanRequest(
                    segment_number=speech.number,
                    segment_id=segment_id,
                    source=speech.source,
                    current_level=speech.planning_level,
                    metric="model_tokens",
                    measured=700,
                    maximum=400,
                ),
            ),
        ).with_identity()
        renderplan_codec.save_preflight(
            report,
            active_voice_root / rendered.variant / chapter / "preflight.toml",
        )
    return root, rendered.variant, rendered.variant_dir, profile


def _run(root: Path, variant: str, *options: str) -> int:
    return main(["replan-book", str(root), "--variant", variant, *options])


def test_replan_book_parser_defaults_and_variant_is_required() -> None:
    args = build_parser().parse_args(
        ["replan-book", "book.ssmdbook", "--variant", "narration--28f616b6fe3b"]
    )
    assert args.command == "replan-book"
    assert args.chapters == "all"
    assert args.renderplan_root is None
    assert args.voicerender_root is None
    assert args.report is None
    assert args.dry_run is False
    assert args.fail_fast is False
    assert args.explain is False
    assert args.json is False
    with pytest.raises(SystemExit):
        build_parser().parse_args(["replan-book", "book.ssmdbook"])


def test_replan_book_human_output_explains_active_transition(tmp_path: Path, capsys) -> None:
    root, variant, _, _ = _prepared(tmp_path)

    result = _run(root, variant, "--chapters", "5", "--explain")

    captured = capsys.readouterr()
    assert result == 0
    assert "UtterPlan book replan" in captured.err
    assert "renderplans:" in captured.err
    assert "preflights:" in captured.err
    assert "previous: sha256:" in captured.err
    assert "replacements: 1" in captured.err
    assert "written: " in captured.err
    assert "active: sha256:" in captured.err
    assert "fallback sentence -> token" in captured.err
    assert "failed:    0" in captured.err


def test_replan_book_json_reports_same_result_and_explanation(tmp_path: Path, capsys) -> None:
    root, variant, variant_dir, _ = _prepared(tmp_path, numbers=(5, 6))

    result = _run(root, variant, "--chapters", "5", "--json", "--explain")

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert captured.err == ""
    assert payload["format"] == "utterplan-replan-book"
    assert payload["variant"] == variant
    assert payload["variant_dir"] == str(variant_dir)
    assert payload["selected_chapter_ids"] == ["chapter-0005"]
    assert payload["written"] == 1
    assert payload["failed"] == 0
    item = payload["outcomes"][0]
    assert item["status"] == "written"
    assert item["replacement_count"] == 1
    assert item["previous_render_plan_id"].startswith("sha256:")
    assert item["render_plan_id"].startswith("sha256:")
    assert "fallback sentence -> token" in item["explanation"]


def test_replan_book_returns_failure_for_stale_reports_in_json(tmp_path: Path, capsys) -> None:
    root, variant, _, _ = _prepared(tmp_path)
    (root / "voicerender" / variant / "chapter-0005" / "preflight.toml").unlink()

    result = _run(root, variant, "--json")

    payload = json.loads(capsys.readouterr().out)
    assert result == 1
    assert payload["failed"] == 1
    assert payload["outcomes"][0]["error_code"] == "renderplan.replan.book.preflight_missing"


def test_replan_book_supports_custom_roots_and_chapter_ranges(tmp_path: Path, capsys) -> None:
    custom_renderplans = tmp_path / "build" / "renderplan"
    custom_voice = tmp_path / "build" / "voicerender"
    root, variant, _, _ = _prepared(
        tmp_path,
        numbers=(5, 6),
        renderplan_root=custom_renderplans,
        voicerender_root=custom_voice,
    )

    result = _run(
        root,
        variant,
        "--chapters",
        "5-6",
        "--renderplan-root",
        str(custom_renderplans),
        "--voicerender-root",
        str(custom_voice),
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "selected:    2" in captured.err
    assert "[1/2] chapter-0005" in captured.err
    assert "[2/2] chapter-0006" in captured.err
    assert "written:   2" in captured.err


def test_replan_book_dry_run_has_no_persisted_children(tmp_path: Path, capsys) -> None:
    root, variant, variant_dir, _ = _prepared(tmp_path)

    result = _run(root, variant, "--dry-run", "--json")

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["dry_run"] is True
    assert payload["planned"] == 1
    assert payload["outcomes"][0]["status"] == "planned"
    assert not Path(payload["outcomes"][0]["renderplan"]).exists()
    assert not list(variant_dir.glob("*.replan-*.renderplan.toml"))
