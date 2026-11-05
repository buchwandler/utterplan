from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from renderplan import PausePolicy, PlanningPolicy, RenderProfile, RoleProfile
from renderplan import codec as renderplan_codec

from utterplan._book_service import BookServiceError, compile_book, render_book
from utterplan.bundle import BundleServiceError, compile_bundle, render_bundle
from utterplan.bundle_inspection import inspect_bundle_compile, inspect_bundle_projection
from utterplan.bundle_role_inventory import load_bundle_role_inventory, sha256_file
from utterplan.config import LinguisticsConfig, PlannerConfig
from utterplan.model import FlowPlan
from utterplan.ssmd_bundle import load_ssmd_bundle

DOCUMENT_FIXTURE = Path(__file__).parent / "fixtures/document-bundle-v1/story.ssmd-bundle"


def _book(root: Path) -> Path:
    chapters = root / "chapters"
    chapters.mkdir(parents=True)
    entries = []
    for number in (5, 6):
        name = f"chapter-{number:04d}.ssmd.md"
        (chapters / name).write_text(
            f'---\nssmd_version: "0.9"\nlanguage: en-US\n---\nChapter {number}.\n',
            encoding="utf-8",
        )
        entries.append(
            {
                "id": f"chapter-{number:04d}",
                "source_number": number,
                "path": f"chapters/{name}",
                "title": f"Chapter {number}",
            }
        )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "format": "ssmdconvert.book",
                "schema_version": 1,
                "ssmd_version": "0.9",
                "chapters": entries,
            }
        ),
        encoding="utf-8",
    )
    return root


def _document(root: Path) -> Path:
    shutil.copytree(DOCUMENT_FIXTURE, root)
    (root / "document.ssmd.md").write_text(
        '---\nssmd_version: "0.9"\nlanguage: en-US\n---\nA bundle document.\n',
        encoding="utf-8",
    )
    return root


def _planner_config() -> PlannerConfig:
    return PlannerConfig(
        language="en-US",
        text_preparation="identity",
        linguistics=LinguisticsConfig(use_spacy=False),
    )


def _profile(path: Path, *, voice: str = "test") -> RenderProfile:
    profile = RenderProfile(
        roles={
            "narrator": RoleProfile(language="en-US", binding={"engine": "test", "voice": voice})
        },
        default_role="narrator",
        planning=PlanningPolicy(split="sentence", capacity_fallback=("token",)),
        pauses=PausePolicy(mode="manual", durations_ms={"sentence": 250}),
    )
    renderplan_codec.save_profile(profile, path)
    return profile


@pytest.mark.parametrize("kind", ["book", "document"])
def test_compile_bundle_dispatches_both_kinds_and_returns_uniform_result(
    tmp_path: Path, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = (
        _book(tmp_path / "novel.ssmd-bundle")
        if kind == "book"
        else _document(tmp_path / "story.ssmd-bundle")
    )
    starts = []
    loaded_indexes = []

    def tracked_load(path):
        index = load_ssmd_bundle(path)
        loaded_indexes.append(index)
        return index

    for module in (
        "utterplan.bundle",
        "utterplan._book_service",
        "utterplan._document_service",
    ):
        monkeypatch.setattr(f"{module}.load_ssmd_bundle", tracked_load)

    result = compile_bundle(root, planner_config=_planner_config(), on_start=starts.append)

    assert result.kind == kind
    assert result.workspace == root
    assert result.exit_code == 0
    assert result.failed == 0
    assert result.selected_item_ids == (
        ("chapter-0005", "chapter-0006") if kind == "book" else ("document-0001",)
    )
    assert all(outcome.status == "written" for outcome in result.outcomes)
    assert len(starts) == 1
    assert starts[0].kind == kind
    assert starts[0].selected_item_ids == result.selected_item_ids
    assert result.report_path.is_file()
    assert result.role_inventory_path == result.output_dir / "role-inventory.toml"
    assert result.role_inventory_path.is_file()
    inventory = load_bundle_role_inventory(result.role_inventory_path)
    assert inventory.bundle_kind == kind
    assert [item.id for item in inventory.items] == list(result.selected_item_ids)
    assert inventory.manifest_sha256 == sha256_file(root / "manifest.json")
    for item in inventory.items:
        assert item.source_sha256 == sha256_file(root / item.source)
        assert item.plan_id == FlowPlan.load(root / item.plan).plan_id

    assert len(loaded_indexes) == 1


def test_partial_book_compile_leaves_canonical_inventory_absent_or_unchanged(
    tmp_path: Path,
) -> None:
    partial_root = _book(tmp_path / "partial.ssmd-bundle")
    partial = compile_bundle(partial_root, chapters="5", planner_config=_planner_config())
    assert partial.exit_code == 0
    assert partial.role_inventory_path is None
    assert not (partial.output_dir / "role-inventory.toml").exists()

    full_root = _book(tmp_path / "full-then-partial.ssmd-bundle")
    full = compile_bundle(full_root, planner_config=_planner_config())
    assert full.role_inventory_path is not None
    previous = full.role_inventory_path.read_bytes()
    subset = compile_bundle(full_root, chapters="5", planner_config=_planner_config(), force=True)
    assert subset.exit_code == 0
    assert subset.role_inventory_path is None
    assert full.role_inventory_path.read_bytes() == previous


@pytest.mark.parametrize("preexisting", [False, True])
def test_failed_full_book_compile_does_not_replace_existing_inventory(
    tmp_path: Path, preexisting: bool
) -> None:
    root = _book(tmp_path / "failed-full.ssmd-bundle")
    output = root / "utterplan"
    output.mkdir()
    inventory_path = output / "role-inventory.toml"
    previous = b"previous inventory"
    if preexisting:
        inventory_path.write_bytes(previous)
    invalid_source = root / "chapters/chapter-0006.ssmd.md"
    invalid_source.write_text("not valid SSMD", encoding="utf-8")

    failed = compile_bundle(root, planner_config=_planner_config())

    assert failed.exit_code == 1
    assert failed.role_inventory_path is None
    if preexisting:
        assert inventory_path.read_bytes() == previous
    else:
        assert not inventory_path.exists()

    invalid_source.write_text(
        (root / "chapters/chapter-0005.ssmd.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    recovered = compile_bundle(root, planner_config=_planner_config(), force=True)
    assert recovered.exit_code == 0
    assert recovered.role_inventory_path == inventory_path
    assert load_bundle_role_inventory(inventory_path).bundle_kind == "book"
    if preexisting:
        assert inventory_path.read_bytes() != previous


def test_document_bundle_only_accepts_all_chapters_for_compile_and_render(tmp_path: Path) -> None:
    root = _document(tmp_path / "story.ssmd-bundle")

    with pytest.raises(BundleServiceError, match="document bundles only support --chapters all"):
        compile_bundle(root, chapters="1")
    with pytest.raises(BundleServiceError, match="document bundles only support --chapters all"):
        render_bundle(root, profile=tmp_path / "missing.renderprofile.toml", chapters="2")


def test_book_services_reject_document_bundle_direct_calls(tmp_path: Path) -> None:
    root = _document(tmp_path / "story.ssmd-bundle")

    with pytest.raises(BookServiceError, match="bundle manifest format is not a book"):
        compile_book(root)
    with pytest.raises(BookServiceError, match="bundle manifest format is not a book"):
        render_book(root, profile=tmp_path / "missing.renderprofile.toml")


def test_render_bundle_dispatches_book_and_document_with_uniform_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaded_indexes = []

    def tracked_load(path):
        index = load_ssmd_bundle(path)
        loaded_indexes.append(index)
        return index

    for module in (
        "utterplan.bundle",
        "utterplan._book_service",
        "utterplan._document_service",
    ):
        monkeypatch.setattr(f"{module}.load_ssmd_bundle", tracked_load)

    for kind, root in (
        ("book", _book(tmp_path / "novel.ssmd-bundle")),
        ("document", _document(tmp_path / "story.ssmd-bundle")),
    ):
        compile_bundle(root, planner_config=_planner_config())
        profile_path = root / f"{kind}.renderprofile.toml"
        loaded_indexes.clear()
        _profile(profile_path)
        starts = []

        result = render_bundle(root, profile=profile_path, on_start=starts.append)

        assert len(loaded_indexes) == 1
        assert result.kind == kind
        assert result.workspace == root
        assert result.exit_code == 0
        assert result.variant.startswith(f"{kind}--")
        assert len(result.selected_item_ids) == len(result.outputs) == len(result.outcomes)
        assert all(path.is_file() for path in result.output)
        assert all(outcome.status == "written" for outcome in result.outcomes)
        assert result.report_path.is_file()
        assert len(starts) == 1
        assert starts[0].kind == kind
        assert starts[0].output_paths == result.outputs
        assert starts[0].report_path == result.report_path


def _tree_snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        path.relative_to(root).as_posix(): None if path.is_dir() else path.read_bytes()
        for path in sorted(root.rglob("*"))
    }


def test_compile_inspector_tracks_source_and_planner_config_without_writes(tmp_path: Path) -> None:
    root = _book(tmp_path / "inspect.ssmd-bundle")
    config = _planner_config()
    before = _tree_snapshot(root)
    fresh = inspect_bundle_compile(root, planner_config=config)
    assert fresh.state == "not_started"
    assert fresh.recommended_selector == "5-6"
    assert _tree_snapshot(root) == before

    compile_bundle(root, chapters="5", planner_config=config)
    partial = inspect_bundle_compile(root, planner_config=config)
    assert [item.state for item in partial.items] == ["complete", "not_started"]
    assert partial.recommended_selector == "6"
    assert not partial.force_required
    assert partial.replacement_safe

    source = root / "chapters/chapter-0005.ssmd.md"
    source.write_text(
        '---\nssmd_version: "0.9"\nlanguage: en-US\n---\nEdited chapter 5.\n',
        encoding="utf-8",
    )
    stale = inspect_bundle_compile(root, planner_config=config)
    assert [item.state for item in stale.items] == ["stale", "not_started"]
    assert stale.recommended_selector == "5-6"
    assert stale.force_required
    assert stale.replacement_safe

    compile_bundle(root, chapters="5", planner_config=config, force=True)
    assert inspect_bundle_compile(root, chapters="5", planner_config=config).state == "complete"
    changed_config = replace(config, overlap_mode="strict")
    config_stale = inspect_bundle_compile(root, planner_config=changed_config)
    assert config_stale.items[0].state == "stale"
    assert config_stale.recommended_selector == "5-6"
    assert config_stale.force_required
    assert config_stale.replacement_safe
    before = _tree_snapshot(root)
    inspect_bundle_compile(root, planner_config=config)
    assert _tree_snapshot(root) == before


def test_projection_inspector_supports_incremental_extension_and_safe_rebuild(
    tmp_path: Path,
) -> None:
    root = _book(tmp_path / "projection.ssmd-bundle")
    config = _planner_config()
    compile_bundle(root, planner_config=config)
    profile_path = root / "narration.renderprofile.toml"
    profile = _profile(profile_path)
    before = _tree_snapshot(root)

    initial = inspect_bundle_projection(root, profile=profile_path)
    assert initial.state == "not_started"
    assert initial.profile_id == profile.computed_id()
    assert initial.missing_chapters == ("chapter-0005", "chapter-0006")
    assert initial.recommended_selector == "5-6"
    assert not initial.force_required
    assert initial.replacement_safe
    assert _tree_snapshot(root) == before

    render_bundle(root, profile=profile_path, chapters="5")
    first = inspect_bundle_projection(root, profile=profile_path)
    assert first.state == "partial"
    assert first.chapters_in_set == ("chapter-0005",)
    assert first.missing_chapters == ("chapter-0006",)
    assert first.recommended_selector == "6"
    assert not first.force_required
    assert first.replacement_safe
    first_projection_bytes = first.items[0].renderplan_path.read_bytes()

    render_bundle(root, profile=profile_path, chapters="6")
    complete = inspect_bundle_projection(root, profile=profile_path)
    assert complete.state == "complete"
    assert complete.items[0].renderplan_path.read_bytes() == first_projection_bytes
    assert complete.recommended_selector is None
    first_renderplan = complete.items[0].renderplan_path.read_bytes()
    second_renderplan = complete.items[1].renderplan_path.read_bytes()

    source = root / "chapters/chapter-0005.ssmd.md"
    source.write_text(
        '---\nssmd_version: "0.9"\nlanguage: en-US\n---\nEdited chapter 5.\n',
        encoding="utf-8",
    )
    compile_bundle(root, chapters="5", planner_config=config, force=True)
    stale = inspect_bundle_projection(root, profile=profile_path)
    assert stale.stale_chapters == ("chapter-0005",)
    assert stale.recommended_selector == "5"
    assert stale.force_required
    before = _tree_snapshot(root)
    inspect_bundle_projection(root, profile=profile_path)
    assert _tree_snapshot(root) == before

    render_bundle(root, profile=profile_path, chapters="5", force=True)
    rebuilt = inspect_bundle_projection(root, profile=profile_path)
    assert rebuilt.state == "complete"
    assert rebuilt.items[1].renderplan_path.read_bytes() == second_renderplan
    assert rebuilt.items[0].renderplan_path.read_bytes() != first_renderplan

    profile_b_path = root / "alternate.renderprofile.toml"
    profile_b = _profile(profile_b_path, voice="sarah")
    before_alternate_inspect = _tree_snapshot(root)
    alternate = inspect_bundle_projection(root, profile=profile_b_path)
    assert alternate.profile_id == profile_b.computed_id()
    assert alternate.variant != complete.variant
    assert alternate.state == "not_started"
    assert _tree_snapshot(root) == before_alternate_inspect
    shutil.copyfile(profile_b_path, complete.items[0].renderplan_path.parent / "renderprofile.toml")
    mismatch = inspect_bundle_projection(root, profile=profile_path)
    assert profile_b.computed_id() != profile.computed_id()
    assert mismatch.profile_snapshot_mismatch
    assert mismatch.state == "profile_mismatch"
    assert mismatch.recommended_selector is None


def test_document_bundle_inspectors_report_single_item_convergence(tmp_path: Path) -> None:
    root = _document(tmp_path / "story.ssmd-bundle")
    config = _planner_config()
    compile_bundle(root, planner_config=config)
    compiled = inspect_bundle_compile(root, planner_config=config)
    assert compiled.state == "complete"
    assert compiled.recommended_selector is None

    profile_path = root / "document.renderprofile.toml"
    _profile(profile_path)
    missing = inspect_bundle_projection(root, profile=profile_path)
    assert missing.state == "not_started"
    assert missing.recommended_selector == "all"
    render_bundle(root, profile=profile_path)
    projected = inspect_bundle_projection(root, profile=profile_path)
    assert projected.state == "complete"
    assert projected.recommended_selector is None
    assert projected.items[0].render_plan_id is not None
