from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import tomlkit

from utterplan.cli import build_parser, main
from utterplan.model import FlowPlan

FIXTURE = Path(__file__).parent / "fixtures/document-bundle-v1/story.ssmd-bundle"


def _workspace(
    tmp_path: Path, name: str = "story.ssmd-bundle", *, text: str = "Original content."
) -> Path:
    root = tmp_path / name
    shutil.copytree(FIXTURE, root)
    (root / "document.ssmd.md").write_text(
        f'---\nssmd_version: "0.9"\nlanguage: en-US\n---\n\n{text}\n',
        encoding="utf-8",
    )
    return root


def _report(path: Path) -> dict[str, object]:
    return dict(tomlkit.parse(path.read_text(encoding="utf-8")))


def _plan_text(path: Path) -> str:
    plan = FlowPlan.load(path)
    return " ".join(segment.text for unit in plan.flow for segment in unit.segments)


def test_compile_document_writes_default_layout_and_keeps_source_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _workspace(tmp_path)
    manifest = root / "manifest.json"
    source = root / "document.ssmd.md"
    manifest_before = manifest.read_bytes()
    source_before = source.read_bytes()

    result = main(
        ["bundle", "compile", str(root), "--text-preparation", "identity", "--spacy", "off"]
    )

    captured = capsys.readouterr()
    output_dir = root / "utterplan"
    plan_path = output_dir / "document.utterplan.toml"
    report_path = output_dir / "compile-report.toml"
    assert result == 0
    assert captured.out == ""
    assert "UtterPlan bundle compile" in captured.err
    assert f"[1/1] document-0001  {source}" in captured.err
    assert "written:   1" in captured.err
    assert "Original content." in _plan_text(plan_path)
    report = _report(report_path)
    assert report["requested"] == 1
    assert report["written"] == 1
    assert report["item"][0]["id"] == "document-0001"
    assert manifest.read_bytes() == manifest_before
    assert source.read_bytes() == source_before
    assert {entry.name for entry in root.iterdir()} == {
        "manifest.json",
        "document.ssmd.md",
        "utterplan",
    }


def test_compile_document_uses_manifest_kind_with_canonical_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _workspace(tmp_path, "workspace.ssmd-bundle")

    result = main(
        ["bundle", "compile", str(root), "--text-preparation", "identity", "--spacy", "off"]
    )

    assert result == 0
    capsys.readouterr()
    assert (root / "utterplan/document.utterplan.toml").is_file()


def test_compile_document_uses_dirty_current_content_without_refreshing_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _workspace(tmp_path)
    manifest = root / "manifest.json"
    manifest_before = manifest.read_bytes()
    source = root / "document.ssmd.md"
    source.write_text(
        '---\nssmd_version: "0.9"\nlanguage: en-US\n---\n\nEdited current content.\n',
        encoding="utf-8",
    )

    result = main(
        ["bundle", "compile", str(root), "--text-preparation", "identity", "--spacy", "off"]
    )

    assert result == 0
    capsys.readouterr()
    assert "Edited current content." in _plan_text(root / "utterplan/document.utterplan.toml")
    assert manifest.read_bytes() == manifest_before
    assert "Edited current content." in source.read_text(encoding="utf-8")


def test_compile_document_missing_source_fails_before_output_creation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _workspace(tmp_path)
    (root / "document.ssmd.md").unlink()

    result = main(["bundle", "compile", str(root)])

    captured = capsys.readouterr()
    assert result == 2
    assert "bundle item is missing" in captured.err
    assert not (root / "utterplan").exists()


def test_compile_document_malformed_manifest_fails_before_output_creation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _workspace(tmp_path)
    manifest = root / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["format"] = "ssmdconvert.book"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    output_dir = tmp_path / "outside-plans"

    result = main(["bundle", "compile", str(root), "--output-dir", str(output_dir)])

    captured = capsys.readouterr()
    assert result == 2
    assert "bundle manifest chapters must be an array" in captured.err
    assert not output_dir.exists()


def test_compile_document_output_and_report_overrides(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _workspace(tmp_path)
    output_dir = tmp_path / "build" / "plans"
    report = tmp_path / "reports" / "compile.toml"

    result = main(
        [
            "bundle",
            "compile",
            str(root),
            "--output-dir",
            str(output_dir),
            "--report",
            str(report),
            "--text-preparation",
            "identity",
            "--spacy",
            "off",
        ]
    )

    assert result == 0
    captured = capsys.readouterr()
    assert str(output_dir) in captured.err
    assert (output_dir / "document.utterplan.toml").is_file()
    assert report.is_file()
    assert not (root / "utterplan").exists()


def test_compile_document_force_only_replaces_existing_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _workspace(tmp_path)
    output = root / "utterplan/document.utterplan.toml"
    output.parent.mkdir(parents=True)
    output.write_text("sentinel", encoding="utf-8")
    args = ["bundle", "compile", str(root), "--text-preparation", "identity", "--spacy", "off"]

    assert main(args) == 1
    capsys.readouterr()
    assert output.read_text(encoding="utf-8") == "sentinel"

    assert main([*args, "--force"]) == 0
    captured = capsys.readouterr()
    assert "Original content." in _plan_text(output)
    assert "written:   1" in captured.err


def test_compile_rejects_document_item_as_bundle_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _workspace(tmp_path)

    result = main(["bundle", "compile", str(root / "document.ssmd.md")])
    captured = capsys.readouterr()

    assert result == 2
    assert "canonical SSMD bundle root" in captured.err
    assert not (root / "utterplan").exists()


def test_compile_document_uses_only_ssmd_language_or_explicit_fallback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _workspace(tmp_path)
    source = root / "document.ssmd.md"
    source.write_text('---\nssmd_version: "0.9"\n---\n\nNo language.\n', encoding="utf-8")
    args = ["bundle", "compile", str(root), "--text-preparation", "identity", "--spacy", "off"]

    assert main(args) == 1
    capsys.readouterr()
    item = _report(root / "utterplan/compile-report.toml")["item"][0]
    assert item["code"] == "input.language_required"

    assert main([*args, "--language", "en-US"]) == 0
    capsys.readouterr()


def test_bundle_compile_parser_exposes_shared_bundle_options() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "bundle",
            "compile",
            "story.ssmd-bundle",
            "--language",
            "en-US",
            "--text-preparation",
            "identity",
            "--renderability",
            "strict",
            "--spacy",
            "off",
            "--force",
            "--diagnostics",
            "none",
        ]
    )
    assert args.command == "bundle"
    assert args.bundle_command == "compile"
    assert args.workspace == Path("story.ssmd-bundle")
    assert args.chapters == "all"
    assert args.text_preparation == "identity"
    assert args.renderability == "strict"
    assert args.force is True
    with pytest.raises(SystemExit):
        parser.parse_args(["bundle", "compile", "story.ssmd-bundle", "--input-format", "ssmd"])


def test_bundle_render_parser_has_shared_options_and_required_profile() -> None:
    args = build_parser().parse_args(
        [
            "bundle",
            "render",
            "story.ssmd-bundle",
            "--profile",
            "voice.renderprofile.toml",
            "--variant",
            "narration",
            "--force",
        ]
    )
    assert args.command == "bundle"
    assert args.bundle_command == "render"
    assert args.workspace == Path("story.ssmd-bundle")
    assert args.profile == Path("voice.renderprofile.toml")
    assert args.variant == "narration"
    assert args.force is True
    with pytest.raises(SystemExit):
        build_parser().parse_args(["bundle", "render", "story.ssmd-bundle"])


def test_unified_api_preserves_the_core_document_compiler() -> None:
    from utterplan import compile_bundle, compile_document, render_bundle, replan_bundle
    from utterplan.compiler import compile_document as compile_document_core

    assert compile_document is compile_document_core
    assert callable(compile_bundle)
    assert callable(render_bundle)
    assert callable(replan_bundle)
