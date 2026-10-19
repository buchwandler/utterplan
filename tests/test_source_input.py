from __future__ import annotations

import json
from pathlib import Path

import pytest

from utterplan.source_input import SourceInputError, load_source_path

FIXTURE = Path(__file__).parent / "fixtures/ssmdoc-v1/story.ssmdoc"
SSMD = '---\nssmd_version: "0.9"\nlanguage: en-US\n---\n\nA sentence.\n'


def test_loads_ssmdoc_directory_as_current_ssmd_document() -> None:
    loaded = load_source_path(FIXTURE)

    assert loaded.text == (FIXTURE / "document.ssmd.md").read_text(encoding="utf-8")
    assert loaded.input_format == "ssmd"
    assert loaded.source_path == FIXTURE / "document.ssmd.md"
    assert loaded.workspace_root == FIXTURE.resolve()
    assert loaded.workspace_kind == "ssmdoc"


def test_loads_canonical_ssmdoc_document_file() -> None:
    loaded = load_source_path(FIXTURE / "document.ssmd.md")

    assert loaded.input_format == "ssmd"
    assert loaded.workspace_root == FIXTURE.resolve()
    assert loaded.workspace_kind == "ssmdoc"


def test_rejects_unsupported_directory(tmp_path: Path) -> None:
    directory = tmp_path / "ordinary"
    directory.mkdir()

    with pytest.raises(SourceInputError, match="unsupported source directory"):
        load_source_path(directory)


def test_rejects_ssmdbook_as_source_directory(tmp_path: Path) -> None:
    directory = tmp_path / "book"
    directory.mkdir()
    (directory / "manifest.json").write_text(
        json.dumps({"format": "ssmdconvert.book"}), encoding="utf-8"
    )

    with pytest.raises(SourceInputError, match="ssmdconvert.document"):
        load_source_path(directory)


def test_standalone_files_keep_existing_auto_detection(tmp_path: Path) -> None:
    ssmd_path = tmp_path / "chapter.ssmd.md"
    ssmd_path.write_text(SSMD, encoding="utf-8")
    plain_path = tmp_path / "chapter.txt"
    plain_path.write_text("Plain source.", encoding="utf-8")

    assert load_source_path(ssmd_path).input_format == "ssmd"
    assert load_source_path(plain_path).input_format == "plain"


def test_standalone_markdown_detection_and_explicit_override(tmp_path: Path) -> None:
    path = tmp_path / "chapter.md"
    path.write_text(SSMD, encoding="utf-8")

    assert load_source_path(path).input_format == "ssmd"
    assert load_source_path(path, requested_format="plain").input_format == "plain"
    assert load_source_path(path, requested_format="ssmd").input_format == "ssmd"


def test_workspace_format_cannot_be_overridden_to_plain() -> None:
    with pytest.raises(SourceInputError, match="SSMDDoc workspace input is SSMD"):
        load_source_path(FIXTURE, requested_format="plain")


def test_missing_canonical_document_stays_a_read_error(tmp_path: Path) -> None:
    root = tmp_path / "missing.ssmdoc"
    root.mkdir()
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "format": "ssmdconvert.document",
                "schema_version": 1,
                "ssmd_version": "0.9",
                "document": {
                    "id": "document-0001",
                    "path": "document.ssmd.md",
                    "sha256": "a" * 64,
                    "char_count": 0,
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError):
        load_source_path(root)


def test_invalid_utf8_standalone_file_keeps_unicode_error(tmp_path: Path) -> None:
    path = tmp_path / "invalid.ssmd"
    path.write_bytes(b"\xff")

    with pytest.raises(UnicodeDecodeError):
        load_source_path(path)
