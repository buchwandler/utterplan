from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from renderplan import PausePolicy, PlanningPolicy, RenderProfile, RoleProfile
from renderplan import codec as renderplan_codec

from utterplan._book_service import BookServiceError, compile_book, render_book
from utterplan.bundle import BundleServiceError, compile_bundle, render_bundle
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


def _profile(path: Path) -> RenderProfile:
    profile = RenderProfile(
        roles={"narrator": RoleProfile(language="en-US", binding={"engine": "test"})},
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
