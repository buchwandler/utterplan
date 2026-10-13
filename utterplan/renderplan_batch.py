"""UtterPlan-owned metadata and batch projection support for book RenderPlans."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

import tomlkit
from renderplan import (
    RENDERPLAN_SET_FORMAT,
    RENDERPLAN_SET_VERSION,
    RenderPlanSet,
    RenderPlanSetChapter,
    RenderPlanSetError,
    RenderProfile,
    load_renderplan_set,
    renderplan_set_from_dict,
    renderplan_set_to_dict,
    renderplan_set_to_toml,
    save_renderplan_set,
    validate_renderplan_set,
    validate_renderplan_set_profile,
)
from renderplan import codec as renderplan_codec

from ._version import __version__
from .atomic_io import atomic_write_text
from .exceptions import UtterPlanError
from .model import FlowPlan
from .renderplan_export import build_render_plan


def new_renderplan_set(
    *,
    variant: str,
    profile_id: str,
    manifest: str,
    utterplan_dir: str,
    source_profile: str,
    chapters: tuple[RenderPlanSetChapter, ...] = (),
) -> RenderPlanSet:
    """Build a set using the shared contract and UtterPlan producer version."""
    return RenderPlanSet(
        variant=variant,
        profile_fingerprint=profile_id.removeprefix("sha256:")[:12],
        producer_version=__version__,
        manifest=manifest,
        utterplan_dir=utterplan_dir,
        profile_id=profile_id,
        snapshot="renderprofile.toml",
        source_profile=source_profile,
        chapters=chapters,
    )


RenderBatchStatus = Literal["written", "failed", "skipped"]
RenderBatchStage = Literal["load", "projection", "serialization", "write", "index"]


@dataclass(frozen=True, slots=True)
class RenderRequest:
    """One semantic UtterPlan input and its independent RenderPlan output."""

    id: str
    source_number: int
    source_plan: Path
    output: Path
    source_chapter: Path

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("render request id must be non-empty")
        if type(self.source_number) is not int or self.source_number <= 0:
            raise ValueError("render request source_number must be a positive integer")
        object.__setattr__(self, "source_plan", Path(self.source_plan))
        object.__setattr__(self, "output", Path(self.output))
        object.__setattr__(self, "source_chapter", Path(self.source_chapter))


@dataclass(frozen=True, slots=True)
class RenderOutcome:
    """Operational result for one chapter projection; plan objects are not retained."""

    id: str
    source_number: int
    index: int
    total: int | None
    status: RenderBatchStatus
    source_plan: Path
    output: Path
    source_plan_id: str | None = None
    render_plan_id: str | None = None
    stage: RenderBatchStage | None = None
    error_code: str | None = None
    error_message: str | None = None


def render_to_files(
    requests: Sequence[RenderRequest],
    *,
    profile: RenderProfile,
    renderplan_set: RenderPlanSet,
    set_path: str | Path,
    report_path: str | Path,
    force: bool = False,
    fail_fast: bool = False,
    chapter_order: Mapping[str, int] | None = None,
    on_progress: Callable[[RenderOutcome], None] | None = None,
) -> list[RenderOutcome]:
    """Project and persist chapters incrementally, keeping successful outputs on failure."""
    validate_renderplan_set(renderplan_set)
    profile_id = profile.profile_id or profile.computed_id()
    if profile_id != renderplan_set.profile_id:
        raise RenderPlanSetError(
            "renderplan set profile_id does not match the active RenderProfile",
            code="profile.identity_mismatch",
        )
    selected_set_path = Path(set_path)
    selected_report_path = Path(report_path)
    _validate_render_requests(requests, renderplan_set, selected_set_path)

    outcomes: list[RenderOutcome] = []
    _write_render_report(
        selected_report_path,
        outcomes,
        requested=len(requests),
        complete=False,
        value=renderplan_set,
    )
    stopped = False
    active_set = renderplan_set
    for index, request in enumerate(requests, start=1):
        if stopped:
            outcome = RenderOutcome(
                id=request.id,
                source_number=request.source_number,
                index=index,
                total=len(requests),
                status="skipped",
                source_plan=request.source_plan,
                output=request.output,
                error_code="batch.fail_fast",
                error_message="Skipped after an earlier failure because fail_fast is enabled.",
            )
        else:
            outcome, updated_set = _render_one(
                request,
                index=index,
                total=len(requests),
                profile=profile,
                renderplan_set=active_set,
                set_path=selected_set_path,
                force=force,
                chapter_order=chapter_order or {},
            )
            if outcome.status == "written":
                active_set = updated_set
        outcomes.append(outcome)
        _write_render_report(
            selected_report_path,
            outcomes,
            requested=len(requests),
            complete=False,
            value=renderplan_set,
        )
        if on_progress is not None:
            on_progress(outcome)
        if fail_fast and outcome.status == "failed":
            stopped = True

    _write_render_report(
        selected_report_path,
        outcomes,
        requested=len(requests),
        complete=True,
        value=renderplan_set,
    )
    return outcomes


def _validate_render_requests(
    requests: Sequence[RenderRequest], value: RenderPlanSet, set_path: Path
) -> None:
    seen_ids: set[str] = set()
    seen_outputs: set[Path] = set()
    existing_owners = {
        (set_path.parent / chapter.renderplan).resolve(): chapter.id for chapter in value.chapters
    }
    for request in requests:
        output = request.output.resolve()
        if request.id in seen_ids:
            raise RenderPlanSetError(f"duplicate selected chapter id: {request.id}")
        if output in seen_outputs:
            raise RenderPlanSetError(f"duplicate selected RenderPlan output path: {request.output}")
        owner = existing_owners.get(output)
        if owner is not None and owner != request.id:
            raise RenderPlanSetError(
                f"RenderPlan output {request.output} is already assigned to chapter {owner}"
            )
        seen_ids.add(request.id)
        seen_outputs.add(output)


def _render_one(
    request: RenderRequest,
    *,
    index: int,
    total: int,
    profile: RenderProfile,
    renderplan_set: RenderPlanSet,
    set_path: Path,
    force: bool,
    chapter_order: Mapping[str, int],
) -> tuple[RenderOutcome, RenderPlanSet]:
    output = request.output
    if not force and output.exists():
        return (
            _render_failure(
                request,
                index=index,
                total=total,
                stage="write",
                error_code="output.exists",
                error_message=f"output already exists: {output}; use --force to replace it",
            ),
            renderplan_set,
        )
    if not request.source_plan.is_file():
        code = "input.missing" if not request.source_plan.exists() else "input.read_failed"
        return (
            _render_failure(
                request,
                index=index,
                total=total,
                stage="load",
                error_code=code,
                error_message=f"cannot read UtterPlan input: {request.source_plan}",
            ),
            renderplan_set,
        )
    try:
        source_plan = FlowPlan.load(request.source_plan)
    except (OSError, UtterPlanError, ValueError, TypeError) as exc:
        return (
            _render_failure(
                request,
                index=index,
                total=total,
                stage="load",
                error_code=_error_code(exc, "input.plan_invalid"),
                error_message=str(exc),
            ),
            renderplan_set,
        )

    source_plan_id = source_plan.plan_id
    try:
        plan = build_render_plan(source_plan, profile).with_identity()
    except (OSError, ValueError, TypeError) as exc:
        return (
            _render_failure(
                request,
                index=index,
                total=total,
                stage="projection",
                error_code=_error_code(exc, "renderplan.projection_failed"),
                error_message=str(exc),
                source_plan_id=source_plan_id,
            ),
            renderplan_set,
        )

    try:
        renderplan_codec.plan_to_dict(plan)
    except (OSError, ValueError, TypeError) as exc:
        return (
            _render_failure(
                request,
                index=index,
                total=total,
                stage="serialization",
                error_code=_error_code(exc, "renderplan.serialization_failed"),
                error_message=str(exc),
                source_plan_id=source_plan_id,
            ),
            renderplan_set,
        )
    try:
        renderplan_codec.save_plan(plan, output)
    except (OSError, ValueError, TypeError) as exc:
        return (
            _render_failure(
                request,
                index=index,
                total=total,
                stage="write",
                error_code=_error_code(exc, "output.write_failed"),
                error_message=str(exc),
                source_plan_id=source_plan_id,
            ),
            renderplan_set,
        )

    render_plan_id = plan.plan_id or plan.computed_id()
    entry = RenderPlanSetChapter(
        id=request.id,
        source_number=request.source_number,
        source=_path_reference(request.source_chapter, set_path.parent),
        utterplan=_path_reference(request.source_plan, set_path.parent),
        source_plan_id=source_plan_id,
        renderplan=_path_reference(output, set_path.parent),
        render_plan_id=render_plan_id,
    )
    try:
        updated_set = _upsert_renderplan_set(renderplan_set, entry, chapter_order)
        save_renderplan_set(set_path, updated_set)
    except (OSError, ValueError, TypeError) as exc:
        return (
            _render_failure(
                request,
                index=index,
                total=total,
                stage="index",
                error_code=_error_code(exc, "index.write_failed"),
                error_message=str(exc),
                source_plan_id=source_plan_id,
                render_plan_id=render_plan_id,
            ),
            renderplan_set,
        )
    return (
        RenderOutcome(
            id=request.id,
            source_number=request.source_number,
            index=index,
            total=total,
            status="written",
            source_plan=request.source_plan,
            output=output,
            source_plan_id=source_plan_id,
            render_plan_id=render_plan_id,
        ),
        updated_set,
    )


def _upsert_renderplan_set(
    value: RenderPlanSet, entry: RenderPlanSetChapter, chapter_order: Mapping[str, int]
) -> RenderPlanSet:
    previous_order = {chapter.id: index for index, chapter in enumerate(value.chapters)}
    chapters_by_id = {chapter.id: chapter for chapter in value.chapters}
    chapters_by_id[entry.id] = entry
    chapters = tuple(
        sorted(
            chapters_by_id.values(),
            key=lambda chapter: (
                0 if chapter.id in chapter_order else 1,
                chapter_order.get(chapter.id, previous_order.get(chapter.id, len(chapter_order))),
            ),
        )
    )
    return replace(value, chapters=chapters)


def _path_reference(path: Path, base: Path) -> str:
    return Path(os.path.relpath(path.resolve(), start=base.resolve())).as_posix()


def _render_failure(
    request: RenderRequest,
    *,
    index: int,
    total: int,
    stage: RenderBatchStage,
    error_code: str,
    error_message: str,
    source_plan_id: str | None = None,
    render_plan_id: str | None = None,
) -> RenderOutcome:
    return RenderOutcome(
        id=request.id,
        source_number=request.source_number,
        index=index,
        total=total,
        status="failed",
        source_plan=request.source_plan,
        output=request.output,
        source_plan_id=source_plan_id,
        render_plan_id=render_plan_id,
        stage=stage,
        error_code=error_code,
        error_message=error_message,
    )


def _write_render_report(
    path: Path,
    outcomes: Sequence[RenderOutcome],
    *,
    requested: int,
    complete: bool,
    value: RenderPlanSet,
) -> None:
    items: list[dict[str, Any]] = []
    for outcome in outcomes:
        item: dict[str, Any] = {
            "index": outcome.index,
            "id": outcome.id,
            "source_number": outcome.source_number,
            "source": str(outcome.source_plan.resolve()),
            "output": str(outcome.output.resolve()),
            "status": outcome.status,
        }
        if outcome.source_plan_id is not None:
            item["source_plan_id"] = outcome.source_plan_id
        if outcome.render_plan_id is not None:
            item["render_plan_id"] = outcome.render_plan_id
        if outcome.stage is not None:
            item["stage"] = outcome.stage
        if outcome.error_code is not None:
            item["code"] = outcome.error_code
        if outcome.error_message is not None:
            item["message"] = outcome.error_message
        items.append(item)
    counts = {
        status: sum(outcome.status == status for outcome in outcomes)
        for status in ("written", "failed", "skipped")
    }
    report = {
        "format": "utterplan-render-report",
        "version": 1,
        "requested": requested,
        "written": counts["written"],
        "failed": counts["failed"],
        "skipped": counts["skipped"],
        "complete": complete,
        "variant": value.variant,
        "profile_id": value.profile_id,
        "item": items,
    }
    atomic_write_text(path, tomlkit.dumps(report), create_parent=True)


def _error_code(error: Exception, fallback: str) -> str:
    code = getattr(error, "code", None)
    return code if isinstance(code, str) and code else fallback


__all__ = [
    "RENDERPLAN_SET_FORMAT",
    "RENDERPLAN_SET_VERSION",
    "RenderBatchStage",
    "RenderBatchStatus",
    "RenderOutcome",
    "RenderRequest",
    "RenderPlanSet",
    "RenderPlanSetChapter",
    "RenderPlanSetError",
    "load_renderplan_set",
    "new_renderplan_set",
    "renderplan_set_from_dict",
    "renderplan_set_to_dict",
    "renderplan_set_to_toml",
    "save_renderplan_set",
    "validate_renderplan_set",
    "render_to_files",
    "validate_renderplan_set_profile",
]
