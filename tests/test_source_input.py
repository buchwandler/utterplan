from __future__ import annotations

from pathlib import Path

import pytest

from utterplan.source_input import SourceInputError, load_source_path

SSMD = '---\nssmd_version: "0.9"\nlanguage: en-US\n---\n\nA sentence.\n'


def test_standalone_files_keep_existing_auto_detection(tmp_path: Path) -> None:
    ssmd_path = tmp_path / "chapter.ssmd.md"
    ssmd_path.write_text(SSMD, encoding="utf-8")
    plain_path = tmp_path / "chapter.txt"
    plain_path.write_text("Plain source.", encoding="utf-8")

    loaded_ssmd = load_source_path(ssmd_path)
    loaded_plain = load_source_path(plain_path)
    assert loaded_ssmd.text == SSMD
    assert loaded_ssmd.input_format == "ssmd"
    assert loaded_ssmd.source_path == ssmd_path
    assert loaded_plain.input_format == "plain"


def test_standalone_markdown_detection_and_explicit_override(tmp_path: Path) -> None:
    path = tmp_path / "chapter.md"
    path.write_text(SSMD, encoding="utf-8")

    assert load_source_path(path).input_format == "ssmd"
    assert load_source_path(path, requested_format="plain").input_format == "plain"
    assert load_source_path(path, requested_format="ssmd").input_format == "ssmd"


def test_generic_source_loader_rejects_directories_and_bundle_roots(tmp_path: Path) -> None:
    ordinary = tmp_path / "ordinary"
    ordinary.mkdir()
    bundle = tmp_path / "story.ssmd-bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text("{}", encoding="utf-8")

    for path in (ordinary, bundle):
        with pytest.raises(SourceInputError, match="not a regular file"):
            load_source_path(path)


def test_invalid_utf8_standalone_file_keeps_unicode_error(tmp_path: Path) -> None:
    path = tmp_path / "invalid.ssmd"
    path.write_bytes(b"\xff")

    with pytest.raises(UnicodeDecodeError):
        load_source_path(path)
