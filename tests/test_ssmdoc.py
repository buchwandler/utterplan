from __future__ import annotations

import json
from pathlib import Path

import pytest

from utterplan.ssmdoc import (
    SSMDDocError,
    load_ssmdoc_index,
    resolve_ssmdoc_root,
    ssmdoc_document_path,
)

FIXTURE = Path(__file__).parent / "fixtures/ssmdoc-v1/story.ssmdoc"
DOCUMENT_TEXT = '---\nssmd_version: "0.9"\nlanguage: en-US\n---\n\nA sentence.\n'


def _document(
    *,
    document_id: object = "document-0001",
    path: object = "document.ssmd.md",
    sha256: object = "a" * 64,
    char_count: object = 42,
) -> dict[str, object]:
    return {
        "id": document_id,
        "path": path,
        "char_count": char_count,
        "sha256": sha256,
    }


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


def test_ssmdconvert_document_v1_fixture_is_supported() -> None:
    index = load_ssmdoc_index(FIXTURE)

    assert index.root == FIXTURE.resolve()
    assert index.document_id == "document-0001"
    assert index.relative_path == "document.ssmd.md"
    assert index.expected_char_count == 87
    assert (
        index.expected_sha256 == "ed67851d91bb3d82c08020d1cdfef99102632a62dbeea46ee1793cf8fa9a49c3"
    )
    assert ssmdoc_document_path(index) == FIXTURE / "document.ssmd.md"


def test_resolves_ssmdoc_root_and_canonical_document_file(tmp_path: Path) -> None:
    root = tmp_path / "named-without-extension"
    _write_manifest(root, _manifest())

    assert resolve_ssmdoc_root(root) == root.resolve()
    assert resolve_ssmdoc_root(root / "document.ssmd.md") == root.resolve()
    assert load_ssmdoc_index(root / "document.ssmd.md").root == root.resolve()


def test_root_detection_uses_manifest_not_suffix(tmp_path: Path) -> None:
    root = tmp_path / "ordinary-name"
    _write_manifest(root, _manifest())

    assert resolve_ssmdoc_root(root) == root.resolve()


def test_rejects_directory_without_manifest(tmp_path: Path) -> None:
    root = tmp_path / "story.ssmdoc"
    root.mkdir()

    with pytest.raises(SSMDDocError, match="expected manifest.json with format"):
        resolve_ssmdoc_root(root)


def test_rejects_ssmdbook_manifest_as_ssmdoc(tmp_path: Path) -> None:
    root = tmp_path / "book.ssmdbook"
    _write_manifest(root, {"format": "ssmdconvert.book", "schema_version": 1})

    with pytest.raises(SSMDDocError, match="expected manifest.json with format"):
        load_ssmdoc_index(root)


def test_rejects_wrong_format_manifest(tmp_path: Path) -> None:
    root = tmp_path / "wrong-format"
    _write_manifest(root, _manifest(format="other.format"))

    with pytest.raises(SSMDDocError, match="ssmdconvert.document"):
        load_ssmdoc_index(root)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "root must be a JSON object"),
        (b"\xff", "invalid ssmdoc manifest"),
        ("{", "invalid ssmdoc manifest"),
        ('{"format":"ssmdconvert.document","value":NaN}', "non-standard JSON constant"),
        ('{"format":"ssmdconvert.document","value":Infinity}', "non-standard JSON constant"),
        ('{"format":"ssmdconvert.document","value":-Infinity}', "non-standard JSON constant"),
    ],
)
def test_rejects_invalid_manifest_json(
    tmp_path: Path, payload: object | str | bytes, message: str
) -> None:
    root = tmp_path / "bad-json"
    _write_manifest(root, payload)

    with pytest.raises(SSMDDocError, match=message):
        load_ssmdoc_index(root)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("format", "ssmdconvert.book", "ssmdconvert.document"),
        ("schema_version", 2, "schema_version"),
        ("schema_version", True, "schema_version"),
        ("ssmd_version", "1.0", "ssmd_version"),
        ("document", None, "document must be an object"),
    ],
)
def test_rejects_unsupported_manifest_header(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    root = tmp_path / "unsupported-header"
    _write_manifest(root, _manifest(**{field: value}))

    with pytest.raises(SSMDDocError, match=message):
        load_ssmdoc_index(root)


@pytest.mark.parametrize(
    ("field", "manifest_key", "value", "message"),
    [
        ("document_id", "id", "other-document", "document.id"),
        ("path", "path", "other.ssmd.md", "document.path"),
        ("sha256", "sha256", "A" * 64, "sha256"),
        ("sha256", "sha256", "abc", "sha256"),
        ("char_count", "char_count", True, "char_count"),
        ("char_count", "char_count", -1, "char_count"),
    ],
)
def test_rejects_invalid_document_fields(
    tmp_path: Path, field: str, manifest_key: str, value: object, message: str
) -> None:
    root = tmp_path / "invalid-document"
    document = _document()
    document[manifest_key] = value
    _write_manifest(root, _manifest(document=document))

    with pytest.raises(SSMDDocError, match=message):
        load_ssmdoc_index(root)


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "/document.ssmd.md",
        "C:/document.ssmd.md",
        "C:document.ssmd.md",
        "..\\document.ssmd.md",
        "../document.ssmd.md",
        "./document.ssmd.md",
        "document//ssmd.md",
        "document.ssmd.md/",
        "document\x00.ssmd.md",
        "document\\ssmd.md",
    ],
)
def test_rejects_unsafe_or_non_normalized_document_paths(tmp_path: Path, unsafe_path: str) -> None:
    root = tmp_path / "unsafe-path"
    _write_manifest(root, _manifest(document=_document(path=unsafe_path)))

    with pytest.raises(SSMDDocError):
        load_ssmdoc_index(root)


def test_manifest_size_is_bounded_before_json_parsing(tmp_path: Path) -> None:
    root = tmp_path / "large-manifest"
    _write_manifest(root, b" " * (2 * 1024 * 1024 + 1))

    with pytest.raises(SSMDDocError, match="2 MiB size limit"):
        load_ssmdoc_index(root)


def test_missing_document_can_be_returned_for_compile_read_failure(tmp_path: Path) -> None:
    root = tmp_path / "missing-document"
    _write_manifest(root, _manifest())

    index = load_ssmdoc_index(root)

    assert ssmdoc_document_path(index) == root / "document.ssmd.md"


def test_rejects_existing_non_file_document(tmp_path: Path) -> None:
    root = tmp_path / "directory-document"
    _write_manifest(root, _manifest())
    (root / "document.ssmd.md").mkdir()

    with pytest.raises(SSMDDocError, match="not a regular file"):
        ssmdoc_document_path(load_ssmdoc_index(root))


def test_rejects_document_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "symlink-workspace"
    _write_manifest(root, _manifest())
    outside = tmp_path / "outside.ssmd.md"
    outside.write_text(DOCUMENT_TEXT, encoding="utf-8")
    link = root / "document.ssmd.md"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(SSMDDocError, match="escapes workspace root"):
        ssmdoc_document_path(load_ssmdoc_index(root))


def test_rejects_manifest_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "manifest-link-workspace"
    root.mkdir()
    outside = tmp_path / "manifest.json"
    outside.write_text(json.dumps(_manifest()), encoding="utf-8")
    try:
        (root / "manifest.json").symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(SSMDDocError, match="cannot read ssmdoc manifest"):
        load_ssmdoc_index(root)
