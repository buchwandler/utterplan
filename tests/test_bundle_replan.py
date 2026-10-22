from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import tomlkit
from renderplan import PreflightCheck, PreflightReport, ReplanRequest
from renderplan import codec as renderplan_codec

from tests.test_bundle_book_replan import _active_plan, _save_preflight, _setup
from tests.test_bundle_services import _planner_config, _profile
from utterplan._book_replan import BookReplanError, replan_book
from utterplan.bundle import compile_bundle, render_bundle
from utterplan.bundle_replan import BundleReplanError, replan_bundle
from utterplan.ssmd_bundle import load_ssmd_bundle

DOCUMENT_FIXTURE = Path(__file__).parent / "fixtures/document-bundle-v1/story.ssmd-bundle"


def _document_bundle(root: Path) -> Path:
    shutil.copytree(DOCUMENT_FIXTURE, root)
    (root / "document.ssmd.md").write_text(
        '---\nssmd_version: "0.9"\nlanguage: en-US\n---\nA sentence to refine.\n',
        encoding="utf-8",
    )
    return root


def _document_preflight(root: Path, variant: str, active_path: Path) -> Path:
    plan = renderplan_codec.load_plan(active_path)
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
    report = PreflightReport(
        render_plan_id=plan.plan_id or plan.computed_id(),
        source_plan_id=plan.source_plan_id,
        render_profile_id=plan.render_profile_id,
        status="replan",
        checks=(check,),
        replan=(request,),
    ).with_identity()
    path = root / "voicerender" / variant / "document-0001" / "preflight.toml"
    renderplan_codec.save_preflight(report, path)
    return path


def test_replan_bundle_keeps_book_set_selection_and_immutable_child_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, variant, variant_dir, _ = _setup(tmp_path, numbers=(5, 6))
    entry, parent, _ = _active_plan(variant_dir)
    loaded_indexes = []

    def tracked_load(path):
        index = load_ssmd_bundle(path)
        loaded_indexes.append(index)
        return index

    monkeypatch.setattr("utterplan.bundle_replan.load_ssmd_bundle", tracked_load)
    monkeypatch.setattr("utterplan._book_replan.load_ssmd_bundle", tracked_load)
    preflight_path = _save_preflight(root / "voicerender", variant, entry.id, parent)
    starts = []

    result = replan_bundle(root, variant=variant, chapters="5", on_start=starts.append)
    assert len(loaded_indexes) == 1

    assert result.kind == "book"
    assert result.selected_item_ids == ("chapter-0005",)
    assert result.exit_code == 0
    assert result.outcomes[0].status == "written"
    assert result.outcomes[0].preflight == preflight_path
    assert (
        result.active_reference == result.workspace / "renderplan" / variant / "renderplan-set.toml"
    )
    assert starts[0].kind == "book"
    assert starts[0].selected_item_ids == ("chapter-0005",)
    assert (variant_dir / "renderplan-set.toml").is_file()
    assert (variant_dir / entry.renderplan).is_file()


def test_document_replan_refines_one_item_and_updates_active_plan_reference(tmp_path: Path) -> None:
    root = _document_bundle(tmp_path / "story.ssmd-bundle")
    compile_bundle(root, planner_config=_planner_config())
    profile_path = root / "narration.renderprofile.toml"
    _profile(profile_path)
    rendered = render_bundle(root, profile=profile_path)
    active_path = rendered.outputs[0]
    previous = renderplan_codec.load_plan(active_path)
    active_bytes = active_path.read_bytes()
    preflight_path = _document_preflight(root, rendered.variant, active_path)

    dry_run = replan_bundle(root, variant=rendered.variant, dry_run=True)

    assert dry_run.kind == "document"
    assert dry_run.selected_item_ids == ("document-0001",)
    assert dry_run.planned == 1
    assert dry_run.outcomes[0].preflight == preflight_path
    assert active_path.read_bytes() == active_bytes
    assert not list(active_path.parent.glob("*.replan-*.renderplan.toml"))

    result = replan_bundle(root, variant=rendered.variant)

    outcome = result.outcomes[0]
    assert result.exit_code == 0
    assert result.written == 1
    assert result.active_reference == active_path
    assert outcome.status == "written"
    assert outcome.previous_render_plan_id == previous.plan_id
    assert outcome.previous_renderplan is not None and outcome.previous_renderplan.is_file()
    assert renderplan_codec.load_plan(outcome.previous_renderplan).plan_id == previous.plan_id
    assert outcome.renderplan is not None and outcome.renderplan.is_file()
    assert renderplan_codec.load_plan(outcome.renderplan).plan_id == outcome.render_plan_id
    assert renderplan_codec.load_plan(active_path).plan_id == outcome.render_plan_id
    report = tomlkit.parse(result.report_path.read_text(encoding="utf-8"))
    assert report["format"] == "utterplan-replan-bundle-report"
    assert report["kind"] == "document"
    assert report["selected_item_ids"] == ["document-0001"]
    assert report["item"][0]["active_renderplan"]

    stale = replan_bundle(root, variant=rendered.variant)
    assert stale.outcomes[0].status == "failed"
    assert stale.outcomes[0].error_code == "renderplan.replan.bundle.preflight_stale"
    assert renderplan_codec.load_plan(active_path).plan_id == outcome.render_plan_id


def test_document_replan_rejects_non_all_selector(tmp_path: Path) -> None:
    root = _document_bundle(tmp_path / "story.ssmd-bundle")
    with pytest.raises(BundleReplanError, match="document bundles only support --chapters all"):
        replan_bundle(root, variant="any", chapters="1")


def test_book_replan_rejects_document_bundle_direct_call(tmp_path: Path) -> None:
    root = _document_bundle(tmp_path / "story.ssmd-bundle")

    with pytest.raises(BookReplanError, match="bundle manifest format is not a book"):
        replan_book(root, variant="not-a-book")
