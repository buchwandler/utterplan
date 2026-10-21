from __future__ import annotations

import json
from pathlib import Path

import pytest

from utterplan.ssmd_bundle import (
    SsmdBundleError,
    bundle_item_path,
    load_ssmd_bundle,
    resolve_ssmd_bundle_root,
)


def _book_manifest(chapters: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "format": "ssmdconvert.book",
        "schema_version": 1,
        "ssmd_version": "0.9",
        "chapters": chapters
        if chapters is not None
        else [
            {
                "id": "chapter-0005",
                "source_number": 5,
                "title": "Chapter 5",
                "path": "chapters/chapter-0005.ssmd.md",
                "sha256": "a" * 64,
            }
        ],
    }


def _document_manifest(**document_updates: object) -> dict[str, object]:
    document: dict[str, object] = {
        "id": "document-0001",
        "path": "document.ssmd.md",
        "sha256": "b" * 64,
        "char_count": 12,
    }
    document.update(document_updates)
    return {
        "format": "ssmdconvert.document",
        "schema_version": 1,
        "ssmd_version": "0.9",
        "metadata": {"title": "Story", "language": "en-US"},
        "document": document,
    }


def _write_manifest(root: Path, manifest: object) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_loads_book_manifest_to_common_bundle_items(tmp_path: Path) -> None:
    root = tmp_path / "novel.ssmd-bundle"
    _write_manifest(root, _book_manifest())

    index = load_ssmd_bundle(root)

    assert index.root == root.resolve()
    assert index.manifest_path == root.resolve() / "manifest.json"
    assert index.kind == "book"
    assert index.items[0].id == "chapter-0005"
    assert index.items[0].relative_path == "chapters/chapter-0005.ssmd.md"
    assert index.items[0].source_number == 5
    assert index.items[0].title == "Chapter 5"
    assert index.items[0].expected_sha256 == "a" * 64
    assert bundle_item_path(index, index.items[0]) == root / "chapters/chapter-0005.ssmd.md"


def test_loads_document_as_single_item_with_source_number_one(tmp_path: Path) -> None:
    root = tmp_path / "story.ssmd-bundle"
    _write_manifest(root, _document_manifest())

    index = load_ssmd_bundle(root)

    assert index.kind == "document"
    assert len(index.items) == 1
    assert index.items[0].id == "document-0001"
    assert index.items[0].relative_path == "document.ssmd.md"
    assert index.items[0].source_number == 1
    assert index.items[0].title == "Story"
    assert index.items[0].expected_sha256 == "b" * 64


def test_manifest_format_is_authoritative_not_workspace_contents(tmp_path: Path) -> None:
    root = tmp_path / "not-a-book-by-name.ssmd-bundle"
    _write_manifest(root, _document_manifest())
    (root / "chapters").mkdir()
    (root / "extra.ssmd.md").write_text("extra", encoding="utf-8")

    assert load_ssmd_bundle(root).kind == "document"


def test_rejects_non_root_workspace_inputs(tmp_path: Path) -> None:
    root = tmp_path / "story.ssmd-bundle"
    _write_manifest(root, _document_manifest())
    (root / "document.ssmd.md").write_text("source", encoding="utf-8")
    (root / "chapters").mkdir()

    with pytest.raises(SsmdBundleError, match="canonical SSMD bundle root"):
        resolve_ssmd_bundle_root(root / "chapters")
    with pytest.raises(SsmdBundleError, match="canonical SSMD bundle root"):
        resolve_ssmd_bundle_root(root / "document.ssmd.md")
    with pytest.raises(SsmdBundleError, match="canonical SSMD bundle root"):
        resolve_ssmd_bundle_root(tmp_path / "legacy-workspace")


def test_rejects_bundle_root_without_manifest_or_regular_root_directory(tmp_path: Path) -> None:
    root = tmp_path / "empty.ssmd-bundle"
    root.mkdir()
    with pytest.raises(SsmdBundleError, match="expected a directory.*manifest.json"):
        load_ssmd_bundle(root)
    with pytest.raises(SsmdBundleError, match="expected a directory.*manifest.json"):
        load_ssmd_bundle(tmp_path / "missing.ssmd-bundle")


def test_unknown_manifest_format_has_actionable_error(tmp_path: Path) -> None:
    root = tmp_path / "future.ssmd-bundle"
    _write_manifest(root, {"format": "future.bundle"})

    with pytest.raises(
        SsmdBundleError, match="unsupported bundle format.*ssmdconvert.book.*ssmdconvert.document"
    ):
        load_ssmd_bundle(root)


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../outside.ssmd.md",
        "chapters/../outside.ssmd.md",
        "/absolute.ssmd.md",
        "C:/absolute.ssmd.md",
        "chapters\\chapter.ssmd.md",
        "chapters//chapter.ssmd.md",
        "chapters/./chapter.ssmd.md",
        "chapters/chapter.ssmd.md/",
    ],
)
def test_rejects_unsafe_book_manifest_paths(tmp_path: Path, unsafe_path: str) -> None:
    root = tmp_path / "unsafe.ssmd-bundle"
    entry = {
        "id": "chapter-0001",
        "source_number": 1,
        "title": "Chapter",
        "path": unsafe_path,
    }
    _write_manifest(root, _book_manifest([entry]))

    with pytest.raises(SsmdBundleError):
        load_ssmd_bundle(root)


@pytest.mark.parametrize("field", ["id", "source_number", "path"])
def test_rejects_duplicate_book_identity_fields(tmp_path: Path, field: str) -> None:
    root = tmp_path / "duplicates.ssmd-bundle"
    first = {
        "id": "chapter-one",
        "source_number": 1,
        "title": "One",
        "path": "chapters/one.ssmd.md",
    }
    second = {
        "id": "chapter-two",
        "source_number": 2,
        "title": "Two",
        "path": "chapters/two.ssmd.md",
    }
    second[field] = first[field]
    _write_manifest(root, _book_manifest([first, second]))

    with pytest.raises(SsmdBundleError, match="duplicate bundle"):
        load_ssmd_bundle(root)


def test_rejects_escaping_item_symlink(tmp_path: Path) -> None:
    root = tmp_path / "link.ssmd-bundle"
    index_manifest = _book_manifest()
    _write_manifest(root, index_manifest)
    source = root / "chapters/chapter-0005.ssmd.md"
    source.parent.mkdir(parents=True)
    outside = tmp_path / "outside.ssmd.md"
    outside.write_text("outside", encoding="utf-8")
    try:
        source.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    index = load_ssmd_bundle(root)
    with pytest.raises(SsmdBundleError, match="escapes workspace root"):
        bundle_item_path(index, index.items[0])


def test_rejects_manifest_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "manifest-link.ssmd-bundle"
    root.mkdir()
    outside = tmp_path / "outside-manifest.json"
    outside.write_text(json.dumps(_book_manifest()), encoding="utf-8")
    try:
        (root / "manifest.json").symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(SsmdBundleError, match="cannot read bundle manifest"):
        load_ssmd_bundle(root)
