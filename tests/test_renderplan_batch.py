from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import tomlkit
from renderplan import PausePolicy, PlanningPolicy, RenderProfile, RoleProfile
from renderplan import codec as renderplan_codec

from utterplan import FlowPlan, FlowSegment, FlowUnit, TokenView
from utterplan.renderplan_batch import (
    RenderPlanSet,
    RenderPlanSetChapter,
    RenderPlanSetError,
    RenderRequest,
    load_renderplan_set,
    new_renderplan_set,
    render_to_files,
    renderplan_set_from_dict,
    renderplan_set_to_dict,
    save_renderplan_set,
    validate_renderplan_set_profile,
)


def _profile(binding: str = "fixture") -> RenderProfile:
    return RenderProfile(
        roles={"narrator": RoleProfile(language="en-US", binding={"engine": binding})},
        default_role="narrator",
        planning=PlanningPolicy(split="sentence"),
        pauses=PausePolicy(mode="manual"),
    ).with_identity()


def _chapter(
    *,
    chapter_id: str = "chapter-0005",
    source_number: int = 5,
    output: str = "chapter-0005.renderplan.toml",
) -> RenderPlanSetChapter:
    return RenderPlanSetChapter(
        id=chapter_id,
        source_number=source_number,
        source="../../chapters/chapter-0005.ssmd.md",
        utterplan="../../utterplan/chapter-0005.utterplan.toml",
        source_plan_id="sha256:" + "1" * 64,
        renderplan=output,
        render_plan_id="sha256:" + "2" * 64,
    )


def _set(profile: RenderProfile | None = None) -> RenderPlanSet:
    selected = profile or _profile()
    return new_renderplan_set(
        variant="narration",
        profile_id=selected.profile_id or selected.computed_id(),
        manifest="../../manifest.json",
        utterplan_dir="../../utterplan",
        source_profile="../../narration.renderprofile.toml",
        chapters=(_chapter(),),
    )


def test_renderplan_set_toml_roundtrip_and_atomic_write(tmp_path: Path) -> None:
    original = _set()
    destination = tmp_path / "variant" / "renderplan-set.toml"

    save_renderplan_set(destination, original)

    loaded = load_renderplan_set(destination)
    assert loaded == original
    assert loaded.profile_fingerprint == loaded.profile_id.removeprefix("sha256:")[:12]
    assert loaded.chapters == (_chapter(),)
    assert "[[chapter]]" in destination.read_text(encoding="utf-8")


def test_renderplan_set_rejects_profile_fingerprint_mismatch() -> None:
    raw = renderplan_set_to_dict(_set())
    raw["profile_fingerprint"] = "f" * 12

    with pytest.raises(RenderPlanSetError, match="does not match"):
        renderplan_set_from_dict(raw)


def test_renderplan_set_rejects_unknown_and_missing_fields() -> None:
    raw = renderplan_set_to_dict(_set())
    raw["unexpected"] = True
    with pytest.raises(RenderPlanSetError, match="unknown field"):
        renderplan_set_from_dict(raw)

    del raw["unexpected"]
    del raw["profile"]
    with pytest.raises(RenderPlanSetError, match="missing required field"):
        renderplan_set_from_dict(raw)


def test_renderplan_set_rejects_duplicate_chapter_ids_and_renderplan_paths() -> None:
    original = _set()
    with pytest.raises(RenderPlanSetError, match="duplicate chapter id"):
        replace(original, chapters=(_chapter(), _chapter(source_number=6)))

    with pytest.raises(RenderPlanSetError, match="duplicate renderplan path"):
        replace(
            original,
            chapters=(
                _chapter(),
                _chapter(chapter_id="chapter-0006", source_number=6),
            ),
        )


def test_renderplan_set_profile_and_snapshot_identity_are_verified(tmp_path: Path) -> None:
    original_profile = _profile()
    snapshot = tmp_path / "renderprofile.toml"
    renderplan_codec.save_profile(original_profile, snapshot)
    value = _set(original_profile)
    identity = original_profile.profile_id or original_profile.computed_id()

    assert (
        validate_renderplan_set_profile(value, snapshot, expected_profile_id=identity)
        == original_profile
    )

    other_profile = _profile("other")
    other_identity = other_profile.profile_id or other_profile.computed_id()
    with pytest.raises(RenderPlanSetError, match="does not match the active"):
        validate_renderplan_set_profile(value, snapshot, expected_profile_id=other_identity)

    other_set = _set(other_profile)
    with pytest.raises(RenderPlanSetError, match="snapshot identity"):
        validate_renderplan_set_profile(other_set, snapshot, expected_profile_id=other_identity)


def test_load_renderplan_set_fails_closed_on_malformed_toml(tmp_path: Path) -> None:
    path = tmp_path / "renderplan-set.toml"
    path.write_text("format = [", encoding="utf-8")

    with pytest.raises(RenderPlanSetError, match="cannot read renderplan set"):
        load_renderplan_set(path)


def _request(root: Path, number: int, *, missing: bool = False) -> RenderRequest:
    source_plan_path = root / "utterplan" / f"chapter-{number:04d}.utterplan.toml"
    source_chapter_path = root / "chapters" / f"chapter-{number:04d}.ssmd.md"
    source_chapter_path.parent.mkdir(parents=True, exist_ok=True)
    source_chapter_path.write_text(f"Chapter {number}.", encoding="utf-8")
    if not missing:
        source_plan_path.parent.mkdir(parents=True, exist_ok=True)
        text = f"Chapter {number}."
        source = FlowPlan(
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
        source.save(source_plan_path)
    return RenderRequest(
        id=f"chapter-{number:04d}",
        source_number=number,
        source_plan=source_plan_path,
        output=root / "renderplan" / "narration" / f"chapter-{number:04d}.renderplan.toml",
        source_chapter=source_chapter_path,
    )


def test_render_batch_persists_plans_and_upserts_in_manifest_order(tmp_path: Path) -> None:
    profile = _profile()
    initial = replace(
        _set(profile),
        chapters=(
            _chapter(
                chapter_id="chapter-0006",
                source_number=6,
                output="chapter-0006.renderplan.toml",
            ),
        ),
    )
    set_path = tmp_path / "renderplan" / "narration" / "renderplan-set.toml"
    report_path = set_path.parent / "render-report.toml"
    save_renderplan_set(set_path, initial)
    requests = [_request(tmp_path, 7), _request(tmp_path, 5)]

    outcomes = render_to_files(
        requests,
        profile=profile,
        renderplan_set=initial,
        set_path=set_path,
        report_path=report_path,
        chapter_order={"chapter-0005": 0, "chapter-0006": 1, "chapter-0007": 2},
    )

    assert [outcome.status for outcome in outcomes] == ["written", "written"]
    updated = load_renderplan_set(set_path)
    assert [chapter.id for chapter in updated.chapters] == [
        "chapter-0005",
        "chapter-0006",
        "chapter-0007",
    ]
    for outcome in outcomes:
        assert outcome.render_plan_id is not None
        saved = renderplan_codec.load_plan(outcome.output)
        assert saved.plan_id == outcome.render_plan_id
        assert saved.render_profile_id == profile.profile_id
    report = tomlkit.parse(report_path.read_text(encoding="utf-8")).unwrap()
    assert report["complete"] is True
    assert report["requested"] == 2
    assert report["written"] == 2
    assert report["failed"] == 0


@pytest.mark.parametrize(
    ("fail_fast", "expected"),
    [
        (False, ["written", "failed", "written"]),
        (True, ["written", "failed", "skipped"]),
    ],
)
def test_render_batch_continues_or_skips_and_records_report(
    tmp_path: Path, fail_fast: bool, expected: list[str]
) -> None:
    profile = _profile()
    initial = replace(_set(profile), chapters=())
    set_path = tmp_path / "renderplan" / "narration" / "renderplan-set.toml"
    report_path = set_path.parent / "render-report.toml"
    save_renderplan_set(set_path, initial)
    requests = [_request(tmp_path, 5), _request(tmp_path, 6, missing=True), _request(tmp_path, 7)]

    outcomes = render_to_files(
        requests,
        profile=profile,
        renderplan_set=initial,
        set_path=set_path,
        report_path=report_path,
        fail_fast=fail_fast,
        chapter_order={"chapter-0005": 0, "chapter-0006": 1, "chapter-0007": 2},
    )

    assert [outcome.status for outcome in outcomes] == expected
    report = tomlkit.parse(report_path.read_text(encoding="utf-8")).unwrap()
    assert report["complete"] is True
    assert report["written"] == expected.count("written")
    assert report["failed"] == 1
    assert report["skipped"] == expected.count("skipped")
    assert report["item"][1]["stage"] == "load"
    assert report["item"][1]["code"] == "input.missing"
    assert [chapter.id for chapter in load_renderplan_set(set_path).chapters] == [
        "chapter-0005"
    ] + (["chapter-0007"] if not fail_fast else [])


def test_render_batch_protects_existing_output_unless_force_is_enabled(tmp_path: Path) -> None:
    profile = _profile()
    initial = replace(_set(profile), chapters=())
    set_path = tmp_path / "renderplan" / "narration" / "renderplan-set.toml"
    report_path = set_path.parent / "render-report.toml"
    save_renderplan_set(set_path, initial)
    request = _request(tmp_path, 5)
    request.output.parent.mkdir(parents=True, exist_ok=True)
    request.output.write_text("keep this", encoding="utf-8")

    protected = render_to_files(
        [request],
        profile=profile,
        renderplan_set=initial,
        set_path=set_path,
        report_path=report_path,
    )
    assert protected[0].status == "failed"
    assert protected[0].error_code == "output.exists"
    assert request.output.read_text(encoding="utf-8") == "keep this"
    assert load_renderplan_set(set_path).chapters == ()

    forced = render_to_files(
        [request],
        profile=profile,
        renderplan_set=initial,
        set_path=set_path,
        report_path=report_path,
        force=True,
    )
    assert forced[0].status == "written"
    assert renderplan_codec.load_plan(request.output).plan_id == forced[0].render_plan_id
    assert [item.id for item in load_renderplan_set(set_path).chapters] == ["chapter-0005"]


def test_render_batch_reports_invalid_utterplan_input(tmp_path: Path) -> None:
    profile = _profile()
    initial = replace(_set(profile), chapters=())
    set_path = tmp_path / "renderplan" / "narration" / "renderplan-set.toml"
    report_path = set_path.parent / "render-report.toml"
    save_renderplan_set(set_path, initial)
    request = _request(tmp_path, 5, missing=True)
    request.source_plan.parent.mkdir(parents=True, exist_ok=True)
    request.source_plan.write_text("not a valid flowplan", encoding="utf-8")

    outcomes = render_to_files(
        [request],
        profile=profile,
        renderplan_set=initial,
        set_path=set_path,
        report_path=report_path,
    )

    assert outcomes[0].status == "failed"
    assert outcomes[0].stage == "load"
    assert outcomes[0].error_code
    assert load_renderplan_set(set_path).chapters == ()


@pytest.mark.parametrize(
    "unsafe_path", ["../manifest.json", "/tmp/plan.toml", "a/../b.toml", "a\\b.toml"]
)
def test_renderplan_set_rejects_renderplan_paths_outside_variant(unsafe_path: str) -> None:
    original = _set()
    chapter = replace(_chapter(), renderplan=unsafe_path)

    with pytest.raises(RenderPlanSetError, match="normalized relative path"):
        replace(original, chapters=(chapter,))


def test_renderplan_set_requires_canonical_profile_snapshot_path() -> None:
    with pytest.raises(RenderPlanSetError, match="canonical"):
        replace(_set(), snapshot="../outside.renderprofile.toml")
