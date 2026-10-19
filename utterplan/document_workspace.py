"""Orchestration services for compiling editable SSMDDoc workspaces."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .batch import BatchProgressCallback, CompileOutcome, CompileRequest, compile_to_files
from .config import PlannerConfig
from .ssmdoc import SSMDDocError, load_ssmdoc_index, ssmdoc_document_path


class DocumentWorkspaceServiceError(ValueError):
    """A document workspace request is invalid or unsafe to execute."""


@dataclass(frozen=True, slots=True)
class DocumentCompileRequest:
    """Options for compiling one editable SSMDDoc workspace."""

    workspace: Path
    output_dir: Path | None = None
    report: Path | None = None
    language: str | None = None
    force: bool = False
    diagnostics: Literal["errors", "warnings", "all", "none"] = "errors"
    planner_config: PlannerConfig | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace", Path(self.workspace))
        if self.output_dir is not None:
            object.__setattr__(self, "output_dir", Path(self.output_dir))
        if self.report is not None:
            object.__setattr__(self, "report", Path(self.report))
        if self.diagnostics not in {"errors", "warnings", "all", "none"}:
            raise ValueError("diagnostics must be 'errors', 'warnings', 'all', or 'none'")


@dataclass(frozen=True, slots=True)
class DocumentCompileStart:
    """Resolved document source and artifact locations announced before compilation."""

    workspace: Path
    document_id: str
    source_path: Path
    output_dir: Path
    report_path: Path
    dirty: bool | None = None


@dataclass(frozen=True, slots=True)
class DocumentCompileResult:
    """Resolved artifacts and the single document compilation outcome."""

    workspace: Path
    document_id: str
    source_path: Path
    output_dir: Path
    plan_path: Path
    report_path: Path
    outcome: CompileOutcome

    @property
    def failed(self) -> int:
        return int(self.outcome.status == "failed")

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0


DocumentCompileStartCallback = Callable[[DocumentCompileStart], None]


def compile_ssmdoc(
    workspace: str | Path,
    *,
    output_dir: str | Path | None = None,
    report: str | Path | None = None,
    language: str | None = None,
    planner_config: PlannerConfig | None = None,
    force: bool = False,
    diagnostics: Literal["errors", "warnings", "all", "none"] = "errors",
    on_progress: BatchProgressCallback | None = None,
    on_start: DocumentCompileStartCallback | None = None,
) -> DocumentCompileResult:
    """Compile the current canonical SSMD document and write a one-item report."""
    request = DocumentCompileRequest(
        workspace=Path(workspace),
        output_dir=Path(output_dir) if output_dir is not None else None,
        report=Path(report) if report is not None else None,
        language=language,
        planner_config=planner_config,
        force=force,
        diagnostics=diagnostics,
    )
    try:
        index = load_ssmdoc_index(request.workspace)
        source_path = ssmdoc_document_path(index)
    except SSMDDocError as exc:
        raise DocumentWorkspaceServiceError(str(exc)) from exc

    output_path = request.output_dir or (index.root / ".readio" / "utterplan")
    plan_path = output_path / f"{index.document_id}.utterplan.toml"
    report_path = request.report or (output_path / "compile-report.toml")
    _preflight_outputs(index.manifest_path, source_path, output_path, plan_path, report_path)

    compile_request = CompileRequest(
        id=index.document_id,
        source=source_path,
        output=plan_path,
        input_format="ssmd",
        fallback_language=request.language,
        source_label=str(source_path),
        require_language=request.language is None,
    )
    config = request.planner_config or PlannerConfig(language=request.language or "en-US")
    if on_start is not None:
        on_start(
            DocumentCompileStart(
                workspace=index.root,
                document_id=index.document_id,
                source_path=source_path,
                output_dir=output_path,
                report_path=report_path,
            )
        )

    outcomes = tuple(
        compile_to_files(
            [compile_request],
            config=config,
            fail_fast=False,
            force=request.force,
            report_path=report_path,
            on_progress=on_progress,
        )
    )
    outcome = outcomes[0]
    return DocumentCompileResult(
        workspace=index.root,
        document_id=index.document_id,
        source_path=source_path,
        output_dir=output_path,
        plan_path=plan_path,
        report_path=report_path,
        outcome=outcome,
    )


def _preflight_outputs(
    manifest_path: Path,
    source_path: Path,
    output_dir: Path,
    plan_path: Path,
    report_path: Path,
) -> None:
    resolved_manifest = manifest_path.resolve(strict=False)
    resolved_source = source_path.resolve(strict=False)
    resolved_plan = plan_path.expanduser().resolve(strict=False)
    resolved_report = report_path.expanduser().resolve(strict=False)

    if resolved_plan == resolved_report:
        raise DocumentWorkspaceServiceError(
            f"document report path collides with plan output: {report_path}"
        )
    for output in (resolved_plan, resolved_report):
        if output in {resolved_manifest, resolved_source}:
            raise DocumentWorkspaceServiceError(
                f"document output would overwrite source workspace content: {output}"
            )

    expanded_output_dir = output_dir.expanduser()
    if expanded_output_dir.exists() and not expanded_output_dir.is_dir():
        raise DocumentWorkspaceServiceError(
            f"document output directory is not a directory: {expanded_output_dir}"
        )
    for output_path in (plan_path, report_path):
        if output_path.exists() and output_path.is_dir():
            raise DocumentWorkspaceServiceError(
                f"document output path is a directory when a file is expected: {output_path}"
            )


__all__ = [
    "DocumentCompileRequest",
    "DocumentCompileResult",
    "DocumentCompileStart",
    "DocumentCompileStartCallback",
    "DocumentWorkspaceServiceError",
    "compile_ssmdoc",
]
