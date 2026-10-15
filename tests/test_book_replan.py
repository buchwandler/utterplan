from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import pytest
import tomlkit
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
from utterplan.book_replan import BookReplanError, replan_book


def _profile(path: Path, fallback: tuple[str, ...] = ("clause", "token")) -> RenderProfile:
    profile = RenderProfile(
        roles={"narrator": RoleProfile(language="en-US", binding={"engine": "fixture"})},
        default_role="narrator",
        planning=PlanningPolicy(split="sentence", capacity_fallback=fallback),
        pauses=PausePolicy(mode="manual", durations_ms={"clause": 180, "sentence": 300}),
    )
    renderplan_codec.save_profile(profile, path)
    return renderplan_codec.load_profile(path)


def _flow(kind: str = "token", number: int = 5) -> FlowPlan:
    if kind == "clause":
        segments = (
            FlowSegment("one ", "en-US", boundary_after=("clause",)),
            FlowSegment("two ", "en-US", boundary_after=("clause",)),
            FlowSegment("three.", "en-US", boundary_after=("sentence",)),
        )
    else:
        text = f"chapter {number} has one two three four."
        words = ["chapter", str(number), "has", "one", "two", "three", "four."]
        tokens: list[TokenView] = []
        cursor = 0
        for word in words:
            start = text.index(word, cursor)
            end = start + len(word)
            tokens.append(TokenView(start, end))
            cursor = end
        segments = (FlowSegment(text, "en-US", tokens=tuple(tokens), boundary_after=("sentence",)),)
    return FlowPlan(language="en-US", flow=(FlowUnit(segments),))


def _write_book(root: Path, numbers: tuple[int, ...], *, kind: str = "token") -> Path:
    root.mkdir(parents=True)
    chapters: list[dict[str, object]] = []
    plans = root / "utterplan"
    plans.mkdir()
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
        _flow(kind, number).save(plans / f"chapter-{number:04d}.utterplan.toml")
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


def _setup(
    tmp_path: Path,
    *,
    numbers: tuple[int, ...] = (5,),
    kind: str = "token",
    fallback: tuple[str, ...] = ("clause", "token"),
    renderplan_root: Path | None = None,
    voicerender_root: Path | None = None,
) -> tuple[Path, str, Path, RenderProfile]:
    root = _write_book(tmp_path / "book.ssmdbook", numbers, kind=kind)
    profile_path = root / "narration.renderprofile.toml"
    profile = _profile(profile_path, fallback)
    active_renderplan_root = renderplan_root or root / "renderplan"
    rendered = render_book(
        root,
        profile=profile_path,
        chapters="all",
        output_root=active_renderplan_root,
    )
    if voicerender_root is not None:
        (voicerender_root / rendered.variant).mkdir(parents=True, exist_ok=True)
    return root, rendered.variant, rendered.variant_dir, profile


def _preflight(
    plan,
    *,
    status: Literal["replan", "ok", "reject"] = "replan",
    profile_id: str | None = None,
    plan_id: str | None = None,
) -> PreflightReport:
    profile_identity = profile_id or plan.render_profile_id
    if status == "replan":
        speech = plan.speech[0]
        segment_id = speech.segment_id or speech.computed_id()
        check = PreflightCheck(
            segment_number=speech.number,
            segment_id=segment_id,
            status="too_long",
            metric="model_tokens",
            measured=700,
            maximum=400,
            source="fixture-renderer",
        )
        request = ReplanRequest(
            segment_number=speech.number,
            segment_id=segment_id,
            source=speech.source,
            current_level=speech.planning_level,
            metric="model_tokens",
            measured=700,
            maximum=400,
        )
        checks = (check,)
        requests = (request,)
    elif status == "ok":
        checks = tuple(
            PreflightCheck(
                segment_number=speech.number,
                segment_id=speech.segment_id or speech.computed_id(),
                status="ok",
                metric="model_tokens",
                measured=10,
                maximum=400,
                source="fixture-renderer",
            )
            for speech in plan.speech
            if speech.preflight_required
        )
        requests = ()
    else:
        checks = ()
        requests = ()
    return PreflightReport(
        render_plan_id=plan_id or plan.plan_id or plan.computed_id(),
        source_plan_id=plan.source_plan_id,
        render_profile_id=profile_identity,
        status=status,
        checks=checks,
        replan=requests,
    ).with_identity()


def _save_preflight(
    root: Path,
    variant: str,
    chapter: str,
    plan,
    *,
    filename: str = "preflight.toml",
    status: Literal["replan", "ok", "reject"] = "replan",
    profile_id: str | None = None,
    plan_id: str | None = None,
) -> Path:
    path = root / variant / chapter / filename
    renderplan_codec.save_preflight(
        _preflight(plan, status=status, profile_id=profile_id, plan_id=plan_id), path
    )
    return path


def _active_plan(variant_dir: Path, chapter: str = "chapter-0005"):
    collection = load_renderplan_set(variant_dir / "renderplan-set.toml")
    entry = next(item for item in collection.chapters if item.id == chapter)
    return entry, renderplan_codec.load_plan(variant_dir / entry.renderplan), collection


def test_clause_replan_installs_child_and_preserves_parent_and_unselected_entries(
    tmp_path: Path,
) -> None:
    root, variant, variant_dir, _ = _setup(tmp_path, numbers=(5, 6), kind="clause")
    entry, parent, collection = _active_plan(variant_dir)
    unselected = next(item for item in collection.chapters if item.id == "chapter-0006")
    parent_path = variant_dir / entry.renderplan
    parent_bytes = parent_path.read_bytes()
    source_bytes = (root / "utterplan/chapter-0005.utterplan.toml").read_bytes()
    preflight_path = _save_preflight(root / "voicerender", variant, entry.id, parent)

    result = replan_book(root, variant=variant, chapters="5")

    assert result.exit_code == 0
    outcome = result.outcomes[0]
    assert outcome.status == "written"
    assert outcome.replacement_count == 1
    assert outcome.renderplan is not None and ".replan-" in outcome.renderplan.name
    assert outcome.preflight == preflight_path
    child = renderplan_codec.load_plan(outcome.renderplan)
    assert child.plan_id == outcome.render_plan_id
    assert [speech.planning_level for speech in child.speech] == ["clause", "clause", "clause"]
    assert parent_path.read_bytes() == parent_bytes
    assert (root / "utterplan/chapter-0005.utterplan.toml").read_bytes() == source_bytes

    updated = load_renderplan_set(result.set_path)
    active = next(item for item in updated.chapters if item.id == entry.id)
    assert active.renderplan == outcome.renderplan.relative_to(variant_dir).as_posix()
    assert active.render_plan_id == child.plan_id
    assert active.source == entry.source
    assert active.utterplan == entry.utterplan
    assert active.source_plan_id == entry.source_plan_id
    assert updated.profile_id == collection.profile_id
    assert next(item for item in updated.chapters if item.id == unselected.id) == unselected


def test_no_clause_boundary_falls_back_to_legal_token_children(tmp_path: Path) -> None:
    root, variant, variant_dir, _ = _setup(tmp_path, kind="token")
    entry, parent, _ = _active_plan(variant_dir)
    _save_preflight(root / "voicerender", variant, entry.id, parent)

    result = replan_book(root, variant=variant, chapters="5")

    assert result.outcomes[0].status == "written"
    child = renderplan_codec.load_plan(result.outcomes[0].renderplan)
    children = [speech for speech in child.speech if speech.planning_level == "token"]
    assert len(children) >= 2
    assert " ".join(speech.text.strip() for speech in children).startswith("chapter 5 has")


def test_recheck_report_wins_and_repeat_replan_uses_immediately_active_parent(
    tmp_path: Path,
) -> None:
    root, variant, variant_dir, _ = _setup(tmp_path, kind="token")
    entry, parent, _ = _active_plan(variant_dir)
    voice_root = root / "voicerender"
    initial = _save_preflight(voice_root, variant, entry.id, parent)
    recheck = _save_preflight(
        voice_root,
        variant,
        entry.id,
        parent,
        filename="preflight-recheck.toml",
    )

    first = replan_book(root, variant=variant, chapters="5")
    first_child = renderplan_codec.load_plan(first.outcomes[0].renderplan)
    assert first.outcomes[0].preflight == recheck
    assert first.outcomes[0].preflight != initial

    next_recheck = _save_preflight(
        voice_root,
        variant,
        entry.id,
        first_child,
        filename="preflight-recheck.toml",
    )
    second = replan_book(root, variant=variant, chapters="5")
    second_child = renderplan_codec.load_plan(second.outcomes[0].renderplan)
    assert second.outcomes[0].status == "written"
    assert second.outcomes[0].previous_render_plan_id == first_child.plan_id
    assert second.outcomes[0].preflight == next_recheck
    assert second_child.plan_id != first_child.plan_id
    assert (variant_dir / entry.renderplan).is_file()


def test_stale_parent_preflight_cannot_be_reused_after_set_switch(tmp_path: Path) -> None:
    root, variant, variant_dir, _ = _setup(tmp_path, kind="token")
    entry, parent, _ = _active_plan(variant_dir)
    old_report = _save_preflight(root / "voicerender", variant, entry.id, parent)
    first = replan_book(root, variant=variant, chapters="5")
    switched_set = load_renderplan_set(first.set_path)
    switched_entry = next(item for item in switched_set.chapters if item.id == entry.id)

    second = replan_book(root, variant=variant, chapters="5")

    assert second.outcomes[0].status == "failed"
    assert second.outcomes[0].error_code == "renderplan.replan.book.preflight_stale"
    assert second.outcomes[0].error_message is not None
    assert "currently active plan" in second.outcomes[0].error_message
    after = load_renderplan_set(second.set_path)
    assert next(item for item in after.chapters if item.id == entry.id) == switched_entry
    assert old_report.is_file()


@pytest.mark.parametrize(
    ("status", "profile_id", "plan_id", "expected_code"),
    [
        ("ok", None, None, "renderplan.replan.book.preflight_status"),
        ("reject", None, None, "renderplan.replan.book.preflight_status"),
        ("replan", "sha256:" + "f" * 64, None, "renderplan.replan.book.preflight_stale"),
        ("replan", None, "sha256:" + "e" * 64, "renderplan.replan.book.preflight_stale"),
    ],
)
def test_invalid_status_and_identity_preflights_are_rejected(
    tmp_path: Path,
    status: Literal["replan", "ok", "reject"],
    profile_id: str | None,
    plan_id: str | None,
    expected_code: str,
) -> None:
    root, variant, variant_dir, _ = _setup(tmp_path, kind="token")
    entry, parent, _ = _active_plan(variant_dir)
    _save_preflight(
        root / "voicerender",
        variant,
        entry.id,
        parent,
        status=status,
        profile_id=profile_id,
        plan_id=plan_id,
    )

    result = replan_book(root, variant=variant, chapters="5")

    assert result.outcomes[0].status == "failed"
    assert result.outcomes[0].error_code == expected_code
    assert load_renderplan_set(result.set_path).chapters[0] == entry


def test_changed_utterplan_source_is_reported_as_source_stale(tmp_path: Path) -> None:
    root, variant, variant_dir, _ = _setup(tmp_path, kind="token")
    entry, parent, _ = _active_plan(variant_dir)
    _save_preflight(root / "voicerender", variant, entry.id, parent)
    source_path = root / "utterplan" / "chapter-0005.utterplan.toml"
    changed = FlowPlan(
        language="en-US",
        flow=(FlowUnit((FlowSegment("changed source text.", "en-US"),)),),
    )
    changed.save(source_path)

    result = replan_book(root, variant=variant, chapters="5")

    assert result.outcomes[0].error_code == "renderplan.replan.source_stale"
    assert result.outcomes[0].status == "failed"


def test_replan_that_returns_parent_identity_is_a_failure(tmp_path: Path, monkeypatch) -> None:
    root, variant, variant_dir, _ = _setup(tmp_path, kind="token")
    entry, parent, _ = _active_plan(variant_dir)
    _save_preflight(root / "voicerender", variant, entry.id, parent)
    monkeypatch.setattr("utterplan.book_replan.build_render_plan", lambda *args, **kwargs: parent)

    result = replan_book(root, variant=variant, chapters="5")

    assert result.outcomes[0].status == "failed"
    assert result.outcomes[0].error_code == "renderplan.replan.book.child_unchanged"
    assert load_renderplan_set(result.set_path).chapters[0] == entry


def test_dry_run_validates_and_plans_without_writing_child_or_set(tmp_path: Path) -> None:
    root, variant, variant_dir, _ = _setup(tmp_path, kind="token")
    entry, parent, _ = _active_plan(variant_dir)
    _save_preflight(root / "voicerender", variant, entry.id, parent)
    set_path = variant_dir / "renderplan-set.toml"
    set_bytes = set_path.read_bytes()

    result = replan_book(root, variant=variant, chapters="5", dry_run=True)

    outcome = result.outcomes[0]
    assert result.exit_code == 0
    assert result.planned == 1
    assert outcome.status == "planned"
    assert outcome.renderplan is not None and not outcome.renderplan.exists()
    assert set_path.read_bytes() == set_bytes
    assert tomlkit.parse(result.report_path.read_text(encoding="utf-8"))["dry_run"] is True


def test_fail_fast_skips_following_chapters_but_default_continues(tmp_path: Path) -> None:
    root, variant, variant_dir, _ = _setup(tmp_path, numbers=(5, 6), kind="token")
    entry6, plan6, _ = _active_plan(variant_dir, "chapter-0006")
    _save_preflight(root / "voicerender", variant, entry6.id, plan6)

    fail_fast = replan_book(root, variant=variant, chapters="5-6", fail_fast=True)
    assert [outcome.status for outcome in fail_fast.outcomes] == ["failed", "skipped"]
    assert fail_fast.outcomes[1].error_code == "batch.fail_fast"

    # Chapter 6 remains eligible when fail-fast is disabled.
    continuing = replan_book(root, variant=variant, chapters="5-6", fail_fast=False)
    assert [outcome.status for outcome in continuing.outcomes] == ["failed", "written"]


def test_replan_report_is_incremental_then_marked_complete(tmp_path: Path) -> None:
    root, variant, variant_dir, _ = _setup(tmp_path, numbers=(5, 6), kind="token")
    for chapter in ("chapter-0005", "chapter-0006"):
        _, plan, _ = _active_plan(variant_dir, chapter)
        _save_preflight(root / "voicerender", variant, chapter, plan)
    observed: list[tuple[bool, int, int]] = []

    def progress(_outcome) -> None:
        data = tomlkit.parse((variant_dir / "replan-report.toml").read_text(encoding="utf-8"))
        observed.append((data["complete"], data["requested"], len(data["item"])))

    result = replan_book(root, variant=variant, chapters="5-6", on_progress=progress)

    report = tomlkit.parse(result.report_path.read_text(encoding="utf-8"))
    assert observed == [(False, 2, 1), (False, 2, 2)]
    assert report["complete"] is True
    assert report["requested"] == 2
    assert report["written"] == 2
    assert [item["status"] for item in report["item"]] == ["written", "written"]


def test_custom_roots_and_start_callback_resolve_collection_owned_profile(tmp_path: Path) -> None:
    custom_plans = tmp_path / "generated-renderplans"
    custom_voice = tmp_path / "renderer-output"
    root, variant, variant_dir, _ = _setup(
        tmp_path,
        renderplan_root=custom_plans,
        voicerender_root=custom_voice,
    )
    entry, plan, _ = _active_plan(variant_dir)
    preflight = _save_preflight(custom_voice, variant, entry.id, plan)
    starts = []

    result = replan_book(
        root,
        variant=variant,
        chapters="5",
        renderplan_root=custom_plans,
        voicerender_root=custom_voice,
        on_start=starts.append,
    )

    assert result.outcomes[0].status == "written"
    assert result.profile_path == variant_dir / "renderprofile.toml"
    assert starts[0].voicerender_dir == custom_voice / variant
    assert result.outcomes[0].preflight == preflight


def test_missing_preflight_is_distinguished_from_stale_report(tmp_path: Path) -> None:
    root, variant, variant_dir, _ = _setup(tmp_path, kind="token")
    entry, parent, _ = _active_plan(variant_dir)

    missing = replan_book(root, variant=variant, chapters="5")
    assert missing.outcomes[0].error_code == "renderplan.replan.book.preflight_missing"

    _save_preflight(
        root / "voicerender",
        variant,
        entry.id,
        parent,
        plan_id="sha256:" + "d" * 64,
    )
    stale = replan_book(root, variant=variant, chapters="5")
    assert stale.outcomes[0].error_code == "renderplan.replan.book.preflight_stale"


def test_variant_and_missing_set_errors_have_actionable_codes(tmp_path: Path) -> None:
    root = _write_book(tmp_path / "book.ssmdbook", (5,))
    with pytest.raises(BookReplanError) as missing_variant:
        replan_book(root, variant="narration--000000000000")
    assert missing_variant.value.code == "renderplan.replan.book.variant_missing"
