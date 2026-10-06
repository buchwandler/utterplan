"""Incremental, engine-independent compilation of independent documents."""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterable, Sized
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import tomlkit

from .atomic_io import atomic_write_text
from .compiler import InputFormat, compile_document
from .config import PlannerConfig
from .exceptions import (
    PlanFormatError,
    PlanRenderabilityError,
    PlanValidationError,
    UtterPlanError,
)
from .model import Diagnostic
from .renderability import format_renderability_error

BatchStatus = Literal["written", "failed", "skipped"]
BatchStage = Literal["read", "compile", "validation", "serialization", "write", "renderability"]


@dataclass(frozen=True, slots=True)
class CompileRequest:
    """One independent source document and its destination plan file."""

    id: str
    source: str | Path
    output: Path
    input_format: InputFormat | Literal["auto"] = "ssmd"
    fallback_language: str | None = None
    source_label: str | None = None
    require_language: bool = False

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("request id must be non-empty")
        object.__setattr__(self, "output", Path(self.output))


@dataclass(frozen=True, slots=True)
class CompileOutcome:
    """Operational result for one request; it never retains the compiled plan."""

    id: str
    index: int
    total: int | None
    status: BatchStatus
    output: Path
    source_label: str
    plan_id: str | None = None
    segments: int | None = None
    repairs: int = 0
    repair_diagnostics: tuple[Diagnostic, ...] = ()
    units: int | None = None
    stage: BatchStage | None = None
    error_code: str | None = None
    error_message: str | None = None
    line: int | None = None
    column: int | None = None


BatchProgressCallback = Callable[[CompileOutcome], None]


def compile_to_files(
    requests: Iterable[CompileRequest],
    *,
    config: PlannerConfig,
    fail_fast: bool = False,
    force: bool = False,
    report_path: str | Path | None = None,
    on_progress: BatchProgressCallback | None = None,
) -> Generator[CompileOutcome]:
    """Compile and atomically persist each request before advancing to the next.

    Expected document, validation, serialization, and file-write errors become
    failed outcomes. Processing continues by default; unexpected programming and
    callback errors propagate to the caller. Existing output files are protected
    unless ``force`` is explicitly enabled.
    """
    total = len(requests) if isinstance(requests, Sized) else None
    selected_report = Path(report_path) if report_path is not None else None

    def run() -> Generator[CompileOutcome]:
        outcomes: list[CompileOutcome] = []
        if selected_report is not None:
            _write_report(selected_report, outcomes, total=total, complete=False)
        stopped = False
        for index, request in enumerate(requests, start=1):
            if stopped:
                outcome = CompileOutcome(
                    id=request.id,
                    index=index,
                    total=total,
                    status="skipped",
                    output=request.output,
                    source_label=_request_source_label(request),
                    error_code="batch.fail_fast",
                    error_message="Skipped after an earlier failure because fail_fast is enabled.",
                )
            else:
                outcome = _compile_one(
                    request,
                    index=index,
                    total=total,
                    config=config,
                    force=force,
                )
            outcomes.append(outcome)
            if selected_report is not None:
                _write_report(selected_report, outcomes, total=total, complete=False)
            if on_progress is not None:
                on_progress(outcome)
            yield outcome
            if fail_fast and outcome.status == "failed":
                stopped = True
        if selected_report is not None:
            _write_report(selected_report, outcomes, total=total, complete=True)

    return run()


def _compile_one(
    request: CompileRequest,
    *,
    index: int,
    total: int | None,
    config: PlannerConfig,
    force: bool,
) -> CompileOutcome:
    source_label = _request_source_label(request)
    output = request.output
    if not force and output.exists():
        return _write_failure(
            request,
            index=index,
            total=total,
            error=FileExistsError(f"output already exists: {output}; use force=True to replace it"),
        )

    if isinstance(request.source, Path):
        try:
            source = request.source.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            return _read_failure(request, index=index, total=total, error=error)
    else:
        source = request.source

    try:
        input_format = _resolve_input_format(request.input_format, request.source, source)
        if (
            request.require_language
            and request.fallback_language is None
            and input_format == "ssmd"
            and _declared_ssmd_language(source) is None
        ):
            raise PlanFormatError(
                "SSMD input without a header language requires --language",
                code="input.language_required",
                path="$.source",
            )
        if (
            request.require_language
            and request.fallback_language is None
            and input_format == "plain"
        ):
            raise PlanFormatError(
                "plain input requires --language",
                code="input.language_required",
                path="$.source",
            )
    except UtterPlanError as error:
        return _compile_failure(request, index, total, error, stage="compile")

    try:
        result = compile_document(
            source,
            input_format=input_format,
            config=config,
            fallback_language=request.fallback_language,
        )
    except PlanRenderabilityError as error:
        return _compile_failure(request, index, total, error, stage="renderability")
    except UtterPlanError as error:
        return _compile_failure(request, index, total, error, stage="compile")

    plan = result.plan
    try:
        plan.validate()
    except PlanValidationError as error:
        return _compile_failure(request, index, total, error, stage="validation")

    try:
        payload = plan.to_toml()
    except UtterPlanError as error:
        return _compile_failure(request, index, total, error, stage="serialization")

    if not force and output.exists():
        return _write_failure(
            request,
            index=index,
            total=total,
            error=FileExistsError(f"output already exists: {output}; use force=True to replace it"),
        )
    try:
        atomic_write_text(output, payload, create_parent=True)
    except OSError as error:
        return _write_failure(request, index=index, total=total, error=error)

    planning = plan.document_metadata.get("planning", {})
    renderability = planning.get("renderability", {}) if isinstance(planning, dict) else {}
    repairs = renderability.get("repair_count", 0) if isinstance(renderability, dict) else 0
    repair_diagnostics = tuple(
        diagnostic
        for diagnostic in plan.diagnostics
        if diagnostic.code == "planning.renderability.repaired"
    )
    return CompileOutcome(
        id=request.id,
        index=index,
        total=total,
        status="written",
        output=output,
        source_label=source_label,
        plan_id=plan.plan_id,
        segments=len(plan.segments),
        repairs=repairs if isinstance(repairs, int) else 0,
        repair_diagnostics=repair_diagnostics,
        units=len(plan.units),
    )


def _resolve_input_format(
    requested: InputFormat | Literal["auto"], source_ref: str | Path, source: str
) -> InputFormat:
    if requested != "auto":
        return requested
    if isinstance(source_ref, Path):
        name = source_ref.name.lower()
        if name.endswith((".ssmd", ".ssmd.md")):
            return "ssmd"
        if source_ref.suffix.lower() != ".md":
            return "plain"
    return "ssmd" if _declares_ssmd_version(source) else "plain"


def _declares_ssmd_version(source: str) -> bool:
    try:
        from ssmd.frontmatter import FrontMatterError, parse_front_matter
    except ImportError:
        return False
    try:
        front_matter = parse_front_matter(source)
    except FrontMatterError:
        return False
    return front_matter.present and "ssmd_version" in front_matter.data


def _declared_ssmd_language(source: str) -> str | None:
    try:
        from ssmd.frontmatter import FrontMatterError, parse_front_matter
    except ImportError:
        return None
    try:
        front_matter = parse_front_matter(source)
    except FrontMatterError as error:
        raise PlanFormatError(str(error), code=error.code, path="$.source") from error
    value = front_matter.data.get("language") if front_matter.present else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _request_source_label(request: CompileRequest) -> str:
    if request.source_label is not None:
        return request.source_label
    return str(request.source) if isinstance(request.source, Path) else request.id


def _read_failure(
    request: CompileRequest,
    *,
    index: int,
    total: int | None,
    error: OSError | UnicodeError,
) -> CompileOutcome:
    return CompileOutcome(
        id=request.id,
        index=index,
        total=total,
        status="failed",
        output=request.output,
        source_label=_request_source_label(request),
        stage="read",
        error_code="input.decode_failed"
        if isinstance(error, UnicodeError)
        else "input.read_failed",
        error_message=str(error),
    )


def _compile_failure(
    request: CompileRequest,
    index: int,
    total: int | None,
    error: UtterPlanError,
    *,
    stage: Literal["compile", "validation", "serialization", "renderability"],
) -> CompileOutcome:
    source_label = _request_source_label(request)
    issue = error.issues[0] if isinstance(error, PlanRenderabilityError) and error.issues else None
    message = (
        format_renderability_error(error, source_label=source_label)
        if isinstance(error, PlanRenderabilityError)
        else str(error)
    )
    return CompileOutcome(
        id=request.id,
        index=index,
        total=total,
        status="failed",
        output=request.output,
        source_label=source_label,
        stage=stage,
        error_code=getattr(error, "code", type(error).__name__),
        error_message=message,
        line=issue.line if issue is not None else None,
        column=issue.column if issue is not None else None,
    )


def _write_failure(
    request: CompileRequest,
    *,
    index: int,
    total: int | None,
    error: OSError,
) -> CompileOutcome:
    source_label = _request_source_label(request)
    return CompileOutcome(
        id=request.id,
        index=index,
        total=total,
        status="failed",
        output=request.output,
        source_label=source_label,
        stage="write",
        error_code="output.exists" if isinstance(error, FileExistsError) else "output.write_failed",
        error_message=str(error),
    )


def _write_report(
    path: Path,
    outcomes: list[CompileOutcome],
    *,
    total: int | None,
    complete: bool,
) -> None:
    data: dict[str, object] = {
        "format": "utterplan-compile-report",
        "version": 1,
        "written": sum(outcome.status == "written" for outcome in outcomes),
        "failed": sum(outcome.status == "failed" for outcome in outcomes),
        "skipped": sum(outcome.status == "skipped" for outcome in outcomes),
        "complete": complete,
    }
    if total is not None or complete:
        data["requested"] = total if total is not None else len(outcomes)
    items: list[dict[str, object]] = []
    for outcome in outcomes:
        item: dict[str, object] = {
            "index": outcome.index,
            "id": outcome.id,
            "source": outcome.source_label,
            "output": str(outcome.output),
            "status": outcome.status,
        }
        optional: dict[str, object | None] = {
            "plan_id": outcome.plan_id,
            "repair_count": outcome.repairs if outcome.repairs else None,
            "segments": outcome.segments,
            "units": outcome.units,
            "stage": outcome.stage,
            "code": outcome.error_code,
            "message": outcome.error_message,
            "line": outcome.line,
            "column": outcome.column,
        }
        item.update({key: value for key, value in optional.items() if value is not None})
        items.append(item)
    data["item"] = items
    atomic_write_text(path, tomlkit.dumps(data), create_parent=True)


__all__ = [
    "BatchProgressCallback",
    "BatchStage",
    "BatchStatus",
    "CompileOutcome",
    "CompileRequest",
    "compile_to_files",
]
