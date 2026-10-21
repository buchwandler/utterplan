"""Book-level orchestration for deterministic RenderPlan refinement."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal

import tomlkit
from renderplan import (
    RenderPlan,
    RenderPlanSet,
    RenderPlanSetChapter,
    RenderPlanSetError,
    RenderProfile,
    load_renderplan_set,
    save_renderplan_set,
    validate_renderplan_set,
    validate_renderplan_set_profile,
    validate_set_chapter_plan,
)
from renderplan import codec as renderplan_codec

from ._book_service import BookServiceError, _path_is_within
from .atomic_io import atomic_write_text
from .exceptions import UtterPlanError
from .model import FlowPlan
from .renderplan_export import build_render_plan
from .ssmd_bundle import (
    BundleItem,
    SsmdBundleError,
    SsmdBundleIndex,
    load_ssmd_bundle,
    select_bundle_items,
)

ReplanStatus = Literal["written", "planned", "failed", "skipped", "unchanged"]
ReplanStage = Literal["load", "preflight", "projection", "serialization", "write", "index"]


class BookReplanError(BookServiceError):
    """A book replan request cannot be prepared safely."""

    def __init__(self, message: str, *, code: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class BookReplanRequest:
    """Options for refining selected chapters in an existing RenderPlan variant."""

    book: Path
    variant: str
    chapters: str = "all"
    renderplan_root: Path | None = None
    voicerender_root: Path | None = None
    report: Path | None = None
    dry_run: bool = False
    fail_fast: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "book", Path(self.book))
        if not isinstance(self.variant, str) or not self.variant.strip():
            raise ValueError("variant must be a non-empty directory name")
        if self.renderplan_root is not None:
            object.__setattr__(self, "renderplan_root", Path(self.renderplan_root))
        if self.voicerender_root is not None:
            object.__setattr__(self, "voicerender_root", Path(self.voicerender_root))
        if self.report is not None:
            object.__setattr__(self, "report", Path(self.report))


@dataclass(frozen=True, slots=True)
class BookReplanStart:
    """Resolved collection and chapter selection announced before processing."""

    workspace: Path
    chapter_selector: str
    selected_chapter_ids: tuple[str, ...]
    variant: str
    variant_dir: Path
    set_path: Path
    profile_path: Path
    voicerender_dir: Path
    report_path: Path


@dataclass(frozen=True, slots=True)
class ReplanOutcome:
    """Operational result for one chapter; plans themselves are not retained."""

    index: int
    id: str
    source_number: int
    status: ReplanStatus
    utterplan: Path | None
    previous_renderplan: Path | None
    previous_render_plan_id: str | None
    preflight: Path | None
    renderplan: Path | None = None
    render_plan_id: str | None = None
    replacement_count: int = 0
    stage: ReplanStage | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class BookReplanResult:
    """Artifacts and per-chapter outcomes from a book replan operation."""

    workspace: Path
    variant: str
    variant_dir: Path
    set_path: Path
    profile_path: Path
    report_path: Path
    selected_chapter_ids: tuple[str, ...]
    dry_run: bool
    outcomes: tuple[ReplanOutcome, ...]

    @property
    def failed(self) -> int:
        return sum(outcome.status == "failed" for outcome in self.outcomes)

    @property
    def written(self) -> int:
        return sum(outcome.status == "written" for outcome in self.outcomes)

    @property
    def planned(self) -> int:
        return sum(outcome.status == "planned" for outcome in self.outcomes)

    @property
    def skipped(self) -> int:
        return sum(outcome.status == "skipped" for outcome in self.outcomes)

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0


ReplanProgressCallback = Callable[[ReplanOutcome], None]
BookReplanStartCallback = Callable[[BookReplanStart], None]


@dataclass(frozen=True, slots=True)
class _BookContext:
    index: SsmdBundleIndex
    chapters: tuple[BundleItem, ...]
    renderplan_root: Path
    variant_dir: Path
    set_path: Path
    profile_path: Path
    profile: RenderProfile
    renderplan_set: RenderPlanSet
    voicerender_dir: Path
    report_path: Path


class _ReplanProblem(Exception):
    def __init__(self, message: str, *, code: str, stage: ReplanStage) -> None:
        self.code = code
        self.stage = stage
        super().__init__(message)


def replan_book(
    book: str | Path,
    *,
    variant: str,
    chapters: str = "all",
    renderplan_root: str | Path | None = None,
    voicerender_root: str | Path | None = None,
    report: str | Path | None = None,
    dry_run: bool = False,
    fail_fast: bool = False,
    on_progress: ReplanProgressCallback | None = None,
    on_start: BookReplanStartCallback | None = None,
) -> BookReplanResult:
    """Refine selected active RenderPlans using their exact matching preflight reports.

    Each successful chapter is installed incrementally: its immutable child plan is
    validated and written before the corresponding RenderPlanSet entry is atomically
    switched. A failure in one chapter does not discard earlier successful chapters.
    """
    request = BookReplanRequest(
        book=Path(book),
        variant=variant,
        chapters=chapters,
        renderplan_root=Path(renderplan_root) if renderplan_root is not None else None,
        voicerender_root=Path(voicerender_root) if voicerender_root is not None else None,
        report=Path(report) if report is not None else None,
        dry_run=dry_run,
        fail_fast=fail_fast,
    )
    context = _prepare_book(request)
    selected_ids = tuple(chapter.id for chapter in context.chapters)
    _ensure_report_not_input(context)
    if on_start is not None:
        on_start(
            BookReplanStart(
                workspace=context.index.root,
                chapter_selector=request.chapters,
                selected_chapter_ids=selected_ids,
                variant=request.variant,
                variant_dir=context.variant_dir,
                set_path=context.set_path,
                profile_path=context.profile_path,
                voicerender_dir=context.voicerender_dir,
                report_path=context.report_path,
            )
        )

    outcomes: list[ReplanOutcome] = []
    active_set = context.renderplan_set
    stopped = False
    _write_replan_report(
        context.report_path, request, len(context.chapters), outcomes, complete=False
    )
    entries = {entry.id: entry for entry in active_set.chapters}
    for index, chapter in enumerate(context.chapters, start=1):
        entry = entries.get(chapter.id)
        if stopped:
            outcome = ReplanOutcome(
                index=index,
                id=chapter.id,
                source_number=chapter.source_number,
                status="skipped",
                utterplan=None,
                previous_renderplan=None,
                previous_render_plan_id=None,
                preflight=None,
                stage="load",
                error_code="batch.fail_fast",
                error_message="Skipped after an earlier failure because fail_fast is enabled.",
            )
        else:
            outcome, updated_set = _replan_one(
                context,
                active_set,
                entry,
                chapter_id=chapter.id,
                source_number=chapter.source_number,
                index=index,
                dry_run=request.dry_run,
            )
            if outcome.status == "written":
                active_set = updated_set
        outcomes.append(outcome)
        _write_replan_report(
            context.report_path, request, len(context.chapters), outcomes, complete=False
        )
        if on_progress is not None:
            on_progress(outcome)
        if request.fail_fast and outcome.status == "failed":
            stopped = True

    _write_replan_report(
        context.report_path, request, len(context.chapters), outcomes, complete=True
    )
    return BookReplanResult(
        workspace=context.index.root,
        variant=request.variant,
        variant_dir=context.variant_dir,
        set_path=context.set_path,
        profile_path=context.profile_path,
        report_path=context.report_path,
        selected_chapter_ids=selected_ids,
        dry_run=request.dry_run,
        outcomes=tuple(outcomes),
    )


def _prepare_book(request: BookReplanRequest) -> _BookContext:
    try:
        index = load_ssmd_bundle(request.book)
        selected = select_bundle_items(index, request.chapters)
    except SsmdBundleError as exc:
        code = (
            "renderplan.replan.book.chapter_missing"
            if "missing source number" in str(exc)
            else "renderplan.replan.book.variant_missing"
        )
        raise BookReplanError(str(exc), code=code) from exc

    if not _safe_variant_name(request.variant):
        raise BookReplanError(
            f"invalid RenderPlan variant directory name: {request.variant!r}",
            code="renderplan.replan.book.variant_missing",
        )
    root_arg = request.renderplan_root or (index.root / "renderplan")
    renderplan_root = root_arg.expanduser().resolve(strict=False)
    variant_candidate = renderplan_root / request.variant
    if not renderplan_root.is_dir() or not variant_candidate.is_dir():
        raise BookReplanError(
            f"RenderPlan variant does not exist: {variant_candidate}",
            code="renderplan.replan.book.variant_missing",
        )
    try:
        renderplan_root = renderplan_root.resolve(strict=True)
        variant_dir = variant_candidate.resolve(strict=True)
        variant_dir.relative_to(renderplan_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise BookReplanError(
            f"RenderPlan variant escapes its configured root or cannot be resolved: "
            f"{variant_candidate}",
            code="renderplan.replan.book.variant_missing",
        ) from exc
    set_path = variant_dir / "renderplan-set.toml"
    if not set_path.is_file():
        raise BookReplanError(
            f"RenderPlan set index is missing: {set_path}",
            code="renderplan.replan.book.index_missing",
        )
    try:
        renderplan_set = load_renderplan_set(set_path)
    except (OSError, ValueError, TypeError, RenderPlanSetError) as exc:
        raise BookReplanError(
            f"invalid RenderPlan set index {set_path}: {exc}",
            code="renderplan.replan.book.index_missing",
        ) from exc

    expected_variant = f"{renderplan_set.variant}--{renderplan_set.profile_fingerprint}"
    if request.variant != expected_variant:
        raise BookReplanError(
            f"RenderPlan set identity does not match requested variant {request.variant!r}",
            code="renderplan.replan.book.variant_missing",
        )
    profile_path = variant_dir / renderplan_set.snapshot
    try:
        profile = validate_renderplan_set_profile(
            renderplan_set, profile_path, expected_profile_id=renderplan_set.profile_id
        )
    except (OSError, ValueError, TypeError, RenderPlanSetError) as exc:
        raise BookReplanError(
            f"invalid RenderProfile snapshot for variant {request.variant}: {exc}",
            code="renderplan.replan.book.profile_invalid",
        ) from exc

    voice_root_arg = request.voicerender_root or (index.root / "voicerender")
    voicerender_dir = voice_root_arg.expanduser().resolve(strict=False) / request.variant
    report_path = request.report or (variant_dir / "replan-report.toml")
    report_path = report_path.expanduser().resolve(strict=False)
    return _BookContext(
        index=index,
        chapters=selected,
        renderplan_root=renderplan_root,
        variant_dir=variant_dir,
        set_path=set_path,
        profile_path=profile_path,
        profile=profile,
        renderplan_set=renderplan_set,
        voicerender_dir=voicerender_dir,
        report_path=report_path,
    )


def _safe_variant_name(value: str) -> bool:
    return (
        bool(value)
        and value not in {".", ".."}
        and "\x00" not in value
        and "/" not in value
        and "\\" not in value
        and PurePosixPath(value).name == value
        and PureWindowsPath(value).name == value
    )


def _ensure_report_not_input(context: _BookContext) -> None:
    report_key = context.report_path.resolve(strict=False)
    protected = {context.set_path.resolve(strict=False), context.profile_path.resolve(strict=False)}
    protected.update(
        (context.variant_dir / entry.renderplan).resolve(strict=False)
        for entry in context.renderplan_set.chapters
    )
    protected.update(
        (context.variant_dir / entry.utterplan).resolve(strict=False)
        for entry in context.renderplan_set.chapters
    )
    protected.add(context.index.manifest_path.resolve(strict=False))
    if report_key in protected or _path_is_within(report_key, context.index.root / "chapters"):
        raise BookReplanError(
            f"replan report path would overwrite protected workspace content: {context.report_path}",
            code="renderplan.replan.book.install_failed",
        )


def _replan_one(
    context: _BookContext,
    active_set: RenderPlanSet,
    entry: RenderPlanSetChapter | None,
    *,
    chapter_id: str,
    source_number: int,
    index: int,
    dry_run: bool,
) -> tuple[ReplanOutcome, RenderPlanSet]:
    if entry is None or entry.source_number != source_number:
        return (
            ReplanOutcome(
                index=index,
                id=chapter_id,
                source_number=source_number,
                status="failed",
                utterplan=None,
                previous_renderplan=None,
                previous_render_plan_id=None,
                preflight=None,
                stage="load",
                error_code="renderplan.replan.book.chapter_missing",
                error_message=f"chapter {chapter_id} has no matching entry in renderplan-set.toml",
            ),
            active_set,
        )

    utterplan_path = context.variant_dir / PurePosixPath(entry.utterplan)
    previous_path = context.variant_dir / PurePosixPath(entry.renderplan)
    previous_id = entry.render_plan_id
    preflight_path: Path | None = None
    stage: ReplanStage = "load"
    try:
        if not utterplan_path.is_file():
            raise _ReplanProblem(
                f"UtterPlan referenced by the active set is missing: {utterplan_path}",
                code="renderplan.replan.book.plan_invalid",
                stage="load",
            )
        source_plan = FlowPlan.load(utterplan_path)
        if source_plan.plan_id != entry.source_plan_id:
            raise _ReplanProblem(
                "UtterPlan identity differs from the active RenderPlanSet source_plan_id; "
                "regenerate the initial RenderPlan before replanning.",
                code="renderplan.replan.source_stale",
                stage="load",
            )
        if not previous_path.is_file():
            raise _ReplanProblem(
                f"active RenderPlan referenced by the set is missing: {previous_path}",
                code="renderplan.replan.book.plan_invalid",
                stage="load",
            )
        previous = renderplan_codec.load_plan(previous_path)
        if previous.plan_id != entry.render_plan_id:
            raise _ReplanProblem(
                "active RenderPlan identity differs from its RenderPlanSet entry",
                code="renderplan.replan.book.plan_invalid",
                stage="load",
            )
        try:
            validate_set_chapter_plan(active_set, entry, previous)
            previous.validate_against_profile(context.profile)
        except (ValueError, TypeError) as exc:
            raise _ReplanProblem(
                f"active RenderPlan does not validate against its set/profile: {exc}",
                code="renderplan.replan.book.plan_invalid",
                stage="load",
            ) from exc

        stage = "preflight"
        preflight_path, preflight = _find_replan_preflight(context, chapter_id, previous)
        stage = "projection"
        child = build_render_plan(
            source_plan,
            context.profile,
            previous_plan=previous,
            preflight=preflight,
        ).with_identity()
        child_id = child.plan_id or child.computed_id()
        if child_id == previous_id:
            raise _ReplanProblem(
                "valid replan feedback produced the same RenderPlan identity as its parent",
                code="renderplan.replan.book.child_unchanged",
                stage="projection",
            )

        stage = "serialization"
        renderplan_codec.plan_to_dict(child)
        child.validate_against_profile(context.profile)
        child_path = _child_plan_path(context.variant_dir, previous_path, child_id)
        child_relative = child_path.relative_to(context.variant_dir).as_posix()
        if any(
            candidate.id != chapter_id
            and (context.variant_dir / candidate.renderplan).resolve(strict=False)
            == child_path.resolve(strict=False)
            for candidate in active_set.chapters
        ):
            raise _ReplanProblem(
                f"immutable child path is already assigned to another chapter: {child_path}",
                code="renderplan.replan.book.install_failed",
                stage="write",
            )
        replacement = replace(
            entry,
            renderplan=child_relative,
            render_plan_id=child_id,
        )
        updated_set = replace(
            active_set,
            chapters=tuple(
                replacement if item.id == chapter_id else item for item in active_set.chapters
            ),
        )
        try:
            validate_renderplan_set(updated_set)
            validate_set_chapter_plan(updated_set, replacement, child)
        except (ValueError, TypeError) as exc:
            raise _ReplanProblem(
                f"updated RenderPlan set does not validate against child: {exc}",
                code="renderplan.replan.book.install_failed",
                stage="index",
            ) from exc

        if not dry_run:
            stage = "write"
            _write_immutable_child(child, child_path)
            stage = "index"
            try:
                save_renderplan_set(context.set_path, updated_set)
            except (OSError, ValueError, TypeError, RenderPlanSetError) as exc:
                raise _ReplanProblem(
                    f"could not activate validated child RenderPlan: {exc}",
                    code="renderplan.replan.book.install_failed",
                    stage="index",
                ) from exc
            active_set = updated_set
        outcome = ReplanOutcome(
            index=index,
            id=chapter_id,
            source_number=source_number,
            status="planned" if dry_run else "written",
            utterplan=utterplan_path,
            previous_renderplan=previous_path,
            previous_render_plan_id=previous_id,
            preflight=preflight_path,
            renderplan=child_path,
            render_plan_id=child_id,
            replacement_count=len(preflight.replan),
        )
        return outcome, active_set
    except _ReplanProblem as exc:
        problem = exc
    except (OSError, UtterPlanError, ValueError, TypeError, RenderPlanSetError) as exc:
        problem = _ReplanProblem(
            str(exc),
            code=_error_code(exc, "renderplan.replan.book.plan_invalid"),
            stage=stage,
        )

    return (
        ReplanOutcome(
            index=index,
            id=chapter_id,
            source_number=source_number,
            status="failed",
            utterplan=utterplan_path,
            previous_renderplan=previous_path,
            previous_render_plan_id=previous_id,
            preflight=preflight_path,
            stage=problem.stage,
            error_code=problem.code,
            error_message=str(problem),
        ),
        active_set,
    )


def _find_replan_preflight(
    context: _BookContext, chapter_id: str, active_plan: RenderPlan
) -> tuple[Path, Any]:
    output_dir = context.voicerender_dir / chapter_id
    candidates = (
        output_dir / "preflight-recheck.toml",
        output_dir / "preflight.toml",
    )
    existing = False
    exact_invalid: list[str] = []
    exact_wrong_status: list[str] = []
    valid: list[tuple[Path, Any]] = []
    active_id = active_plan.plan_id or active_plan.computed_id()
    for path in candidates:
        if not path.is_file():
            continue
        existing = True
        try:
            preflight = renderplan_codec.load_preflight(path)
        except (OSError, ValueError, TypeError) as exc:
            exact_invalid.append(f"{path.name}: {exc}")
            continue
        if preflight.render_plan_id != active_id:
            continue
        try:
            preflight.validate_against(active_plan)
        except (ValueError, TypeError) as exc:
            exact_invalid.append(f"{path.name}: {exc}")
            continue
        if preflight.status != "replan":
            exact_wrong_status.append(f"{path.name} has status={preflight.status!r}")
            continue
        valid.append((path, preflight))
    if valid:
        # candidates are ordered with immediate recheck evidence first.
        return valid[0]
    if exact_wrong_status:
        raise _ReplanProblem(
            "matching preflight report is not a replan input: " + "; ".join(exact_wrong_status),
            code="renderplan.replan.book.preflight_status",
            stage="preflight",
        )
    if existing:
        detail = "; ".join(exact_invalid)
        message = (
            "available preflight reports belong to an older or invalid RenderPlan; "
            "rerun VoiceRender preflight/render for the currently active plan."
        )
        if detail:
            message += f" Details: {detail}"
        else:
            message = (
                f"No preflight report matching active RenderPlan {active_id} was found for "
                f"{chapter_id}; rerun VoiceRender preflight/render for the currently active plan."
            )
        raise _ReplanProblem(
            message,
            code="renderplan.replan.book.preflight_stale",
            stage="preflight",
        )
    raise _ReplanProblem(
        f"No preflight report matching active RenderPlan {active_id} was found for {chapter_id}.",
        code="renderplan.replan.book.preflight_missing",
        stage="preflight",
    )


def _child_plan_path(variant_dir: Path, previous_path: Path, child_id: str) -> Path:
    filename = previous_path.name
    suffix = ".renderplan.toml"
    stem = filename[: -len(suffix)] if filename.endswith(suffix) else previous_path.stem
    fingerprint = child_id.removeprefix("sha256:")[:12]
    return variant_dir / f"{stem}.replan-{fingerprint}{suffix}"


def _write_immutable_child(plan: RenderPlan, path: Path) -> None:
    if path.exists():
        try:
            existing = renderplan_codec.load_plan(path)
        except (OSError, ValueError, TypeError) as exc:
            raise _ReplanProblem(
                f"immutable child path already exists but is invalid: {path}: {exc}",
                code="renderplan.replan.book.install_failed",
                stage="write",
            ) from exc
        if existing.plan_id != plan.plan_id:
            raise _ReplanProblem(
                f"refusing to overwrite a different immutable RenderPlan: {path}",
                code="renderplan.replan.book.install_failed",
                stage="write",
            )
        return
    try:
        renderplan_codec.save_plan(plan, path)
        persisted = renderplan_codec.load_plan(path)
        if persisted.plan_id != plan.plan_id or persisted != plan:
            raise ValueError("saved child RenderPlan does not match the validated in-memory plan")
    except (OSError, ValueError, TypeError) as exc:
        raise _ReplanProblem(
            f"could not write validated immutable child RenderPlan {path}: {exc}",
            code="renderplan.replan.book.install_failed",
            stage="write",
        ) from exc


def _write_replan_report(
    path: Path,
    request: BookReplanRequest,
    requested: int,
    outcomes: Sequence[ReplanOutcome],
    *,
    complete: bool,
) -> None:
    counts = {
        status: sum(outcome.status == status for outcome in outcomes)
        for status in ("written", "planned", "failed", "skipped", "unchanged")
    }
    items: list[dict[str, Any]] = []
    base = path.parent
    for outcome in outcomes:
        item: dict[str, Any] = {
            "index": outcome.index,
            "id": outcome.id,
            "source_number": outcome.source_number,
            "status": outcome.status,
        }
        for key, value in (
            ("utterplan", outcome.utterplan),
            ("previous_renderplan", outcome.previous_renderplan),
            ("preflight", outcome.preflight),
            ("renderplan", outcome.renderplan),
        ):
            if value is not None:
                item[key] = _report_path(value, base)
        for metadata_key, metadata_value in (
            ("previous_render_plan_id", outcome.previous_render_plan_id),
            ("render_plan_id", outcome.render_plan_id),
            ("replacement_count", outcome.replacement_count),
            ("stage", outcome.stage),
            ("code", outcome.error_code),
            ("message", outcome.error_message),
        ):
            if metadata_value is not None:
                item[metadata_key] = metadata_value
        items.append(item)
    data = {
        "format": "utterplan-replan-report",
        "version": 1,
        "variant": request.variant,
        "requested": requested,
        "written": counts["written"],
        "planned": counts["planned"],
        "failed": counts["failed"],
        "skipped": counts["skipped"],
        "unchanged": counts["unchanged"],
        "complete": complete,
        "dry_run": request.dry_run,
        "item": items,
    }
    try:
        atomic_write_text(path, tomlkit.dumps(data), create_parent=True)
    except OSError as exc:
        raise BookReplanError(
            f"cannot write replan operational report {path}: {exc}",
            code="renderplan.replan.book.install_failed",
        ) from exc


def _report_path(path: Path, base: Path) -> str:
    return Path(
        os.path.relpath(path.resolve(strict=False), start=base.resolve(strict=False))
    ).as_posix()


def _error_code(error: Exception, fallback: str) -> str:
    code = getattr(error, "code", None)
    return code if isinstance(code, str) and code else fallback


__all__ = [
    "BookReplanError",
    "BookReplanRequest",
    "BookReplanResult",
    "BookReplanStart",
    "BookReplanStartCallback",
    "ReplanOutcome",
    "ReplanProgressCallback",
    "ReplanStatus",
    "replan_book",
]
