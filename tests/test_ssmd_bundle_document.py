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

FIXTURE = Path(__file__).parent / "fixtures/document-bundle-v1/story.ssmd-bundle"
DOCUMENT_TEXT = '---\nssmd_version: "0.9"\nlanguage: en-US\n---\n\nA sentence.\n'


def _document(**updates: object) -> dict[str, object]:
    document: dict[str, object] = {
        "id": "document-0001",
        "path": "document.ssmd.md",
        "sha256": "a" * 64,
        "char_count": 42,
    }
    document.update(updates)
    return document


def _manifest(**updates: object) -> dict[str, object]:
    result: dict[str, object] = {
        "format": "ssmdconvert.document",
        "schema_version": 1,
        "ssmd_version": "0.9",
        "metadata": {"title": "Example", "language": "en-US"},
        "document": _document(),
    }
    result.update(updates)
    return result


def _write_manifest(root: Path, data: object | str | bytes) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    if isinstance(data, bytes):
        manifest_path.write_bytes(data)
    elif isinstance(data, str):
        manifest_path.write_text(data, encoding="utf-8")
    else:
        manifest_path.write_text(json.dumps(data), encoding="utf-8")
    return manifest_path


def test_document_v1_fixture_maps_to_one_common_item() -> None:
    index = load_ssmd_bundle(FIXTURE)

    assert index.kind == "document"
    assert index.root == FIXTURE.resolve()
    assert index.items[0].id == "document-0001"
    assert index.items[0].relative_path == "document.ssmd.md"
    assert index.items[0].source_number == 1
    assert index.items[0].title == "UtterPlan document fixture"
    assert (
        index.items[0].expected_sha256
        == "ed67851d91bb3d82c08020d1cdfef99102632a62dbeea46ee1793cf8fa9a49c3"
    )
    assert (
        bundle_item_path(index, index.items[0], require_exists=True) == FIXTURE / "document.ssmd.md"
    )


def test_manifest_item_path_and_optional_fields_are_preserved(tmp_path: Path) -> None:
    root = tmp_path / "nested-source.ssmd-bundle"
    source = root / "content" / "document.ssmd.md"
    source.parent.mkdir(parents=True)
    source.write_text(DOCUMENT_TEXT, encoding="utf-8")
    document = _document(id="document-main", path="content/document.ssmd.md")
    document.pop("sha256")
    document.pop("char_count")
    _write_manifest(root, _manifest(document=document, extra_provenance={"source": "test"}))

    index = load_ssmd_bundle(root)
    item = index.items[0]

    assert item.id == "document-main"
    assert item.relative_path == "content/document.ssmd.md"
    assert item.source_number == 1
    assert item.expected_sha256 is None
    assert bundle_item_path(index, item, require_exists=True) == source


def test_root_resolution_accepts_only_canonical_bundle_root(tmp_path: Path) -> None:
    root = tmp_path / "story.ssmd-bundle"
    _write_manifest(root, _manifest())
    source = root / "document.ssmd.md"
    source.write_text(DOCUMENT_TEXT, encoding="utf-8")

    assert resolve_ssmd_bundle_root(root) == root.resolve()
    with pytest.raises(SsmdBundleError, match="canonical SSMD bundle root"):
        resolve_ssmd_bundle_root(source)
    with pytest.raises(SsmdBundleError, match="canonical SSMD bundle root"):
        resolve_ssmd_bundle_root(tmp_path / "story")


def test_manifest_kind_is_authoritative_and_unknown_formats_fail(tmp_path: Path) -> None:
    root = tmp_path / "book-named.ssmd-bundle"
    _write_manifest(root, _manifest())
    (root / "chapters").mkdir()
    assert load_ssmd_bundle(root).kind == "document"

    unknown = tmp_path / "unknown.ssmd-bundle"
    _write_manifest(unknown, {"format": "future.bundle"})
    with pytest.raises(SsmdBundleError, match="unsupported bundle format"):
        load_ssmd_bundle(unknown)


def test_rejects_invalid_manifest_json_and_nonstandard_constants(tmp_path: Path) -> None:
    root = tmp_path / "bad-json.ssmd-bundle"
    manifest = _write_manifest(root, [])
    with pytest.raises(SsmdBundleError, match="root must be a JSON object"):
        load_ssmd_bundle(root)

    manifest.write_text('{"format":"ssmdconvert.document","value":NaN}', encoding="utf-8")
    with pytest.raises(SsmdBundleError, match="non-standard JSON constant"):
        load_ssmd_bundle(root)

    manifest.write_bytes(b"\xff")
    with pytest.raises(SsmdBundleError, match="invalid bundle manifest"):
        load_ssmd_bundle(root)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"id": ""}, "document.id"),
        ({"id": 42}, "document.id"),
        ({"path": ""}, "document.path"),
        ({"path": "../outside.ssmd.md"}, "document.path"),
        ({"sha256": "A" * 64}, "document.sha256"),
        ({"sha256": "abc"}, "document.sha256"),
        ({"char_count": True}, "char_count"),
        ({"char_count": -1}, "char_count"),
    ],
)
def test_rejects_invalid_document_item_fields(
    tmp_path: Path, updates: dict[str, object], message: str
) -> None:
    root = tmp_path / "invalid.ssmd-bundle"
    document = _document(**updates)
    _write_manifest(root, _manifest(document=document))

    with pytest.raises(SsmdBundleError, match=message):
        load_ssmd_bundle(root)


def test_rejects_wrong_schema_header_and_wrong_manifest_kind(tmp_path: Path) -> None:
    root = tmp_path / "unsupported.ssmd-bundle"
    _write_manifest(root, _manifest(schema_version=2))
    with pytest.raises(SsmdBundleError, match="schema_version"):
        load_ssmd_bundle(root)

    _write_manifest(root, _manifest(format="ssmdconvert.book"))
    with pytest.raises(SsmdBundleError, match="chapters must be an array"):
        load_ssmd_bundle(root)


def test_rejects_missing_item_non_file_and_escaping_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "missing-item.ssmd-bundle"
    _write_manifest(root, _manifest())
    index = load_ssmd_bundle(root)
    with pytest.raises(SsmdBundleError, match="bundle item is missing"):
        bundle_item_path(index, index.items[0], require_exists=True)

    source = root / "document.ssmd.md"
    source.mkdir()
    with pytest.raises(SsmdBundleError, match="not a regular file"):
        bundle_item_path(index, index.items[0], require_exists=True)
    source.rmdir()

    outside = tmp_path / "outside.ssmd.md"
    outside.write_text(DOCUMENT_TEXT, encoding="utf-8")
    try:
        source.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(SsmdBundleError, match="escapes workspace root"):
        bundle_item_path(index, index.items[0])


def test_rejects_manifest_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "manifest-link.ssmd-bundle"
    root.mkdir()
    outside = tmp_path / "manifest.json"
    outside.write_text(json.dumps(_manifest()), encoding="utf-8")
    try:
        (root / "manifest.json").symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(SsmdBundleError, match="cannot read bundle manifest"):
        load_ssmd_bundle(root)
