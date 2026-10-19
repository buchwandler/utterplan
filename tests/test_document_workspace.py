from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import tomlkit

from utterplan.config import LinguisticsConfig, PlannerConfig
from utterplan.document_workspace import (
    DocumentCompileStart,
    DocumentWorkspaceServiceError,
    compile_ssmdoc,
)
from utterplan.model import FlowPlan

FIXTURE = Path(__file__).parent / "fixtures/ssmdoc-v1/story.ssmdoc"


def _ssmd(text: str, *, language: str | None = "en-US") -> str:
    header = '---\nssmd_version: "0.9"\n'
    if language is not None:
        header += f"language: {language}\n"
    return f"{header}---\n\n{text}\n"


def _workspace(
    tmp_path: Path, name: str = "story.ssmdoc", *, text: str = "Original content."
) -> Path:
    root = tmp_path / name
    shutil.copytree(FIXTURE, root)
    (root / "document.ssmd.md").write_text(_ssmd(text), encoding="utf-8")
    return root


def _config() -> PlannerConfig:
    return PlannerConfig(
        language="en-US",
        text_preparation="identity",
        linguistics=LinguisticsConfig(use_spacy=False),
    )


def _report(path: Path) -> dict[str, object]:
    return dict(tomlkit.parse(path.read_text(encoding="utf-8")))


def _plan_text(path: Path) -> str:
    plan = FlowPlan.load(path)
    return " ".join(segment.text for unit in plan.flow for segment in unit.segments)


def test_compile_ssmdoc_writes_default_plan_and_one_item_report_without_source_changes(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    manifest = root / "manifest.json"
    source = root / "document.ssmd.md"
    manifest_before = manifest.read_bytes()
    source_before = source.read_bytes()
    starts: list[DocumentCompileStart] = []
    progress = []

    result = compile_ssmdoc(
        root,
        planner_config=_config(),
        on_start=starts.append,
        on_progress=progress.append,
    )

    output_dir = root / ".readio" / "utterplan"
    assert result.exit_code == 0
    assert result.failed == 0
    assert result.document_id == "document-0001"
    assert result.plan_path == output_dir / "document-0001.utterplan.toml"
    assert result.report_path == output_dir / "compile-report.toml"
    assert result.plan_path.is_file()
    assert result.report_path.is_file()
    assert "Original content." in _plan_text(result.plan_path)
    assert manifest.read_bytes() == manifest_before
    assert source.read_bytes() == source_before
    assert len(starts) == 1 and starts[0].document_id == "document-0001"
    assert starts[0].dirty is None
    assert len(progress) == 1 and progress[0].status == "written"
    report = _report(result.report_path)
    assert report["requested"] == 1
    assert report["written"] == 1
    assert report["failed"] == 0
    assert report["item"][0]["id"] == "document-0001"
    assert report["item"][0]["source"] == str(source)


def test_compile_ssmdoc_uses_edited_content_with_stale_digest(tmp_path: Path) -> None:
    root = _workspace(tmp_path, text="Original content.")
    manifest = root / "manifest.json"
    manifest_before = manifest.read_bytes()
    source = root / "document.ssmd.md"
    source.write_text(_ssmd("Edited current content."), encoding="utf-8")
    source_before = source.read_bytes()

    result = compile_ssmdoc(root, planner_config=_config())

    assert result.exit_code == 0
    assert "Edited current content." in _plan_text(result.plan_path)
    assert manifest.read_bytes() == manifest_before
    assert source.read_bytes() == source_before


def test_missing_document_is_a_reported_read_failure(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    (root / "document.ssmd.md").unlink()

    result = compile_ssmdoc(root, planner_config=_config())

    assert result.exit_code == 1
    assert not result.plan_path.exists()
    item = _report(result.report_path)["item"][0]
    assert item["status"] == "failed"
    assert item["stage"] == "read"


def test_invalid_ssmd_is_a_reported_compile_failure_without_plan(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    source = root / "document.ssmd.md"
    source.write_text('---\nssmd_version: "0.8"\n---\n\nBad dialect.\n', encoding="utf-8")

    result = compile_ssmdoc(root, planner_config=_config())

    assert result.exit_code == 1
    assert not result.plan_path.exists()
    item = _report(result.report_path)["item"][0]
    assert item["status"] == "failed"
    assert item["stage"] == "compile"


def test_existing_plan_is_protected_unless_force_is_used(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    output = root / ".readio" / "utterplan" / "document-0001.utterplan.toml"
    output.parent.mkdir(parents=True)
    output.write_text("sentinel", encoding="utf-8")

    protected = compile_ssmdoc(root, planner_config=_config())

    assert protected.exit_code == 1
    assert output.read_text(encoding="utf-8") == "sentinel"
    assert _report(protected.report_path)["item"][0]["status"] == "failed"

    forced = compile_ssmdoc(root, planner_config=_config(), force=True)

    assert forced.exit_code == 0
    assert "Original content." in _plan_text(output)


def test_output_override_and_report_override_do_not_create_default_layout(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    output_dir = tmp_path / "build" / "plans"
    report = tmp_path / "reports" / "document.toml"

    result = compile_ssmdoc(
        root,
        output_dir=output_dir,
        report=report,
        planner_config=_config(),
    )

    assert result.exit_code == 0
    assert result.output_dir == output_dir
    assert result.report_path == report
    assert result.plan_path.is_file()
    assert report.is_file()
    assert not (root / ".readio" / "utterplan").exists()


def test_output_collisions_are_rejected_before_creating_directories(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    output_dir = tmp_path / "collision-plans"
    plan_path = output_dir / "document-0001.utterplan.toml"

    with pytest.raises(DocumentWorkspaceServiceError, match="report path collides"):
        compile_ssmdoc(
            root,
            output_dir=output_dir,
            report=plan_path,
            planner_config=_config(),
        )
    assert not output_dir.exists()

    with pytest.raises(DocumentWorkspaceServiceError, match="overwrite source workspace"):
        compile_ssmdoc(
            root,
            output_dir=output_dir,
            report=root / "manifest.json",
            planner_config=_config(),
        )
    assert not output_dir.exists()

    with pytest.raises(DocumentWorkspaceServiceError, match="overwrite source workspace"):
        compile_ssmdoc(
            root,
            output_dir=output_dir,
            report=root / "document.ssmd.md",
            planner_config=_config(),
        )
    assert not output_dir.exists()


def test_invalid_manifest_is_rejected_before_output_creation(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    manifest = root / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["format"] = "ssmdconvert.book"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    output_dir = tmp_path / "invalid-plans"

    with pytest.raises(DocumentWorkspaceServiceError, match="ssmdconvert.document"):
        compile_ssmdoc(root, output_dir=output_dir, planner_config=_config())
    assert not output_dir.exists()


def test_ssmd_language_is_authority_and_manifest_language_is_not_fallback(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    result = compile_ssmdoc(root, planner_config=_config())
    assert result.exit_code == 0

    no_header_language = _workspace(tmp_path, "no-language.ssmdoc")
    source = no_header_language / "document.ssmd.md"
    source.write_text(_ssmd("No declared language.", language=None), encoding="utf-8")
    missing_fallback = compile_ssmdoc(no_header_language, planner_config=_config())
    assert missing_fallback.exit_code == 1
    assert _report(missing_fallback.report_path)["item"][0]["code"] == "input.language_required"

    with_fallback = compile_ssmdoc(
        no_header_language,
        language="en-US",
        planner_config=_config(),
        force=True,
    )
    assert with_fallback.exit_code == 0


def test_canonical_document_path_is_accepted_by_service(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    result = compile_ssmdoc(root / "document.ssmd.md", planner_config=_config())

    assert result.exit_code == 0
    assert result.workspace == root.resolve()
