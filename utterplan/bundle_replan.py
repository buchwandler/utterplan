"""Unified bundle replan service for book sets and single-document plans."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import tomlkit
from renderplan import RenderPlan, RenderProfile
from renderplan import codec as renderplan_codec

from ._book_replan import (
    BookReplanError,
    ReplanOutcome,
    ReplanProgressCallback,
    replan_book,
)
from .atomic_io import atomic_write_text
from .model import FlowPlan
from .renderplan_export import build_render_plan
from .renderplan_workspace import profile_fingerprint
from .ssmd_bundle import (
    BundleItem,
    BundleKind,
    SsmdBundleError,
    SsmdBundleIndex,
    bundle_item_path,
    load_ssmd_bundle,
)
from .workspace_paths import renderplan_output_name, utterplan_output_name


class BundleReplanError(ValueError):
    """A bundle replan request cannot be prepared safely."""

    def __init__(self, message: str, *, code: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class BundleReplanStart:
    workspace: Path
    kind: BundleKind
    selector: str
    selected_item_ids: tuple[str, ...]
    variant: str
    active_reference: Path
    profile_path: Path
    voicerender_dir: Path
    report_path: Path


@dataclass(frozen=True, slots=True)
class BundleReplanResult:
    workspace: Path
    kind: BundleKind
    variant: str
    selected_item_ids: tuple[str, ...]
    active_reference: Path
    report_path: Path
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


BundleReplanStartCallback = Callable[[BundleReplanStart], None]


@dataclass(frozen=True, slots=True)
class _DocumentContext:
    index: SsmdBundleIndex
    item: BundleItem
    source_path: Path
    source_plan_path: Path
    variant: str
    variant_dir: Path
    active_path: Path
    profile_path: Path
    profile: RenderProfile
    voicerender_dir: Path
    report_path: Path


class _DocumentReplanProblem(ValueError):
    def __init__(self, message: str, *, code: str, stage: str) -> None:
        self.code = code
        self.stage = stage
        super().__init__(message)


def replan_bundle(
    bundle: str | Path,
    *,
    variant: str,
    chapters: str = "all",
    renderplan_root: str | Path | None = None,
    voicerender_root: str | Path | None = None,
    report: str | Path | None = None,
    dry_run: bool = False,
    fail_fast: bool = False,
    on_progress: ReplanProgressCallback | None = None,
    on_start: BundleReplanStartCallback | None = None,
) -> BundleReplanResult:
    """Refine the active RenderPlan(s) selected by the bundle's manifest format."""
    try:
        index = load_ssmd_bundle(bundle)
    except SsmdBundleError as exc:
        raise BundleReplanError(str(exc), code="renderplan.replan.bundle.invalid") from exc
    selector = chapters.strip()
    if index.kind == "document":
        if selector != "all":
            raise BundleReplanError(
                "document bundles only support --chapters all",
                code="renderplan.replan.bundle.selector_invalid",
            )
        return _replan_document(
            index,
            variant=variant,
            renderplan_root=renderplan_root,
            voicerender_root=voicerender_root,
            report=report,
            dry_run=dry_run,
            on_progress=on_progress,
            on_start=on_start,
        )

    try:
        result = replan_book(
            index.root,
            variant=variant,
            chapters=selector,
            renderplan_root=renderplan_root,
            voicerender_root=voicerender_root,
            report=report,
            dry_run=dry_run,
            fail_fast=fail_fast,
            on_progress=on_progress,
            _index=index,
            on_start=(
                lambda start: (
                    on_start(
                        BundleReplanStart(
                            start.workspace,
                            index.kind,
                            start.chapter_selector,
                            start.selected_chapter_ids,
                            start.variant,
                            start.set_path,
                            start.profile_path,
                            start.voicerender_dir,
                            start.report_path,
                        )
                    )
                    if on_start is not None
                    else None
                )
            ),
        )
    except BookReplanError as exc:
        raise BundleReplanError(str(exc), code=exc.code) from exc
    return BundleReplanResult(
        workspace=result.workspace,
        kind=index.kind,
        variant=result.variant,
        selected_item_ids=result.selected_chapter_ids,
        active_reference=result.set_path,
        report_path=result.report_path,
        dry_run=result.dry_run,
        outcomes=result.outcomes,
    )


def _replan_document(
    index: SsmdBundleIndex,
    *,
    variant: str,
    renderplan_root: str | Path | None,
    voicerender_root: str | Path | None,
    report: str | Path | None,
    dry_run: bool,
    on_progress: ReplanProgressCallback | None,
    on_start: BundleReplanStartCallback | None,
) -> BundleReplanResult:
    try:
        context = _prepare_document(
            index,
            variant=variant,
            renderplan_root=renderplan_root,
            voicerender_root=voicerender_root,
            report=report,
        )
    except _DocumentReplanProblem as exc:
        raise BundleReplanError(str(exc), code=exc.code) from exc
    if on_start is not None:
        on_start(
            BundleReplanStart(
                workspace=index.root,
                kind="document",
                selector="all",
                selected_item_ids=(context.item.id,),
                variant=variant,
                active_reference=context.active_path,
                profile_path=context.profile_path,
                voicerender_dir=context.voicerender_dir,
                report_path=context.report_path,
            )
        )

    _write_document_report(context, (), dry_run=dry_run, complete=False)
    outcome = _replan_document_one(context, dry_run=dry_run)
    _write_document_report(context, (outcome,), dry_run=dry_run, complete=False)
    if on_progress is not None:
        on_progress(outcome)
    _write_document_report(context, (outcome,), dry_run=dry_run, complete=True)
    return BundleReplanResult(
        workspace=index.root,
        kind="document",
        variant=variant,
        selected_item_ids=(context.item.id,),
        active_reference=context.active_path,
        report_path=context.report_path,
        dry_run=dry_run,
        outcomes=(outcome,),
    )


def _prepare_document(
    index: SsmdBundleIndex,
    *,
    variant: str,
    renderplan_root: str | Path | None,
    voicerender_root: str | Path | None,
    report: str | Path | None,
) -> _DocumentContext:
    item = index.items[0]
    if not _safe_variant_name(variant):
        raise _DocumentReplanProblem(
            f"invalid RenderPlan variant directory name: {variant!r}",
            code="renderplan.replan.bundle.variant_invalid",
            stage="load",
        )
    try:
        source_path = bundle_item_path(index, item, require_exists=True)
    except SsmdBundleError as exc:
        raise _DocumentReplanProblem(
            str(exc), code="renderplan.replan.bundle.source_invalid", stage="load"
        ) from exc
    source_plan_dir = index.root / "utterplan"
    source_plan_path = source_plan_dir / utterplan_output_name(source_path)
    root_arg = Path(renderplan_root) if renderplan_root is not None else index.root / "renderplan"
    render_root = root_arg.expanduser().resolve(strict=False)
    variant_candidate = render_root / variant
    if not render_root.is_dir() or not variant_candidate.is_dir() or variant_candidate.is_symlink():
        raise _DocumentReplanProblem(
            f"RenderPlan variant does not exist or is unsafe: {variant_candidate}",
            code="renderplan.replan.bundle.variant_missing",
            stage="load",
        )
    try:
        variant_dir = variant_candidate.resolve(strict=True)
        variant_dir.relative_to(render_root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise _DocumentReplanProblem(
            f"RenderPlan variant escapes its configured root: {variant_candidate}",
            code="renderplan.replan.bundle.variant_missing",
            stage="load",
        ) from exc
    profile_path = variant_dir / "renderprofile.toml"
    active_path = variant_dir / renderplan_output_name(source_path)
    if active_path.is_symlink() or not active_path.is_file():
        raise _DocumentReplanProblem(
            f"active document RenderPlan is missing or unsafe: {active_path}",
            code="renderplan.replan.bundle.plan_missing",
            stage="load",
        )
    try:
        profile = renderplan_codec.load_profile(profile_path)
        profile_id = profile.profile_id or profile.computed_id()
        active = renderplan_codec.load_plan(active_path)
        active.validate_against_profile(profile)
    except (OSError, ValueError, TypeError) as exc:
        raise _DocumentReplanProblem(
            f"invalid active RenderPlan or profile snapshot: {exc}",
            code="renderplan.replan.bundle.plan_invalid",
            stage="load",
        ) from exc
    if not variant.endswith("--" + profile_fingerprint(profile_id)):
        raise _DocumentReplanProblem(
            "RenderPlan variant identity does not match its profile snapshot",
            code="renderplan.replan.bundle.variant_mismatch",
            stage="load",
        )
    voice_root = (
        Path(voicerender_root).expanduser().resolve(strict=False)
        if voicerender_root is not None
        else index.root / "voicerender"
    )
    voicerender_dir = voice_root / variant
    report_path = (
        Path(report).expanduser().resolve(strict=False)
        if report is not None
        else variant_dir / "replan-report.toml"
    )
    protected = {
        index.manifest_path.resolve(strict=False),
        source_path.resolve(strict=False),
        source_plan_path.resolve(strict=False),
        profile_path.resolve(strict=False),
        active_path.resolve(strict=False),
    }
    if report_path in protected or report_path.is_dir():
        raise _DocumentReplanProblem(
            f"replan report path collides with protected input: {report_path}",
            code="renderplan.replan.bundle.report_collision",
            stage="load",
        )
    return _DocumentContext(
        index=index,
        item=item,
        source_path=source_path,
        source_plan_path=source_plan_path,
        variant=variant,
        variant_dir=variant_dir,
        active_path=active_path,
        profile_path=profile_path,
        profile=profile,
        voicerender_dir=voicerender_dir,
        report_path=report_path,
    )


def _replan_document_one(context: _DocumentContext, *, dry_run: bool) -> ReplanOutcome:
    item = context.item
    active_path = context.active_path
    active: RenderPlan | None = None
    preflight_path: Path | None = None
    previous_reference = active_path
    stage = "load"
    try:
        if not context.source_plan_path.is_file():
            raise _DocumentReplanProblem(
                f"UtterPlan referenced by the document bundle is missing: {context.source_plan_path}",
                code="renderplan.replan.bundle.source_plan_missing",
                stage="load",
            )
        source_plan = FlowPlan.load(context.source_plan_path)
        active = renderplan_codec.load_plan(active_path)
        if active.source_plan_id != source_plan.plan_id:
            raise _DocumentReplanProblem(
                "UtterPlan identity differs from the active RenderPlan source_plan_id; "
                "recompile and render the current document before replanning.",
                code="renderplan.replan.bundle.source_stale",
                stage="load",
            )
        stage = "preflight"
        preflight_path, preflight = _find_document_preflight(context, active)
        stage = "projection"
        child = build_render_plan(
            source_plan,
            context.profile,
            previous_plan=active,
            preflight=preflight,
        ).with_identity()
        child_id = child.plan_id or child.computed_id()
        active_id = active.plan_id or active.computed_id()
        if child_id == active_id:
            raise _DocumentReplanProblem(
                "valid replan feedback produced the same RenderPlan identity as its parent",
                code="renderplan.replan.bundle.child_unchanged",
                stage="projection",
            )
        stage = "serialization"
        renderplan_codec.plan_to_dict(child)
        child.validate_against_profile(context.profile)
        child_path = _child_plan_path(active_path, child_id)
        parent_path = _parent_snapshot_path(active_path, active_id)
        if child_path.resolve(strict=False) == active_path.resolve(strict=False):
            raise _DocumentReplanProblem(
                "immutable child RenderPlan path collides with the active plan",
                code="renderplan.replan.bundle.install_failed",
                stage="write",
            )
        if dry_run:
            previous_reference = active_path
        else:
            stage = "write"
            _write_immutable_child(active, parent_path)
            _write_immutable_child(child, child_path)
            _replace_active_document_plan(child, active_path)
            previous_reference = parent_path
        return ReplanOutcome(
            index=1,
            id=item.id,
            source_number=1,
            status="planned" if dry_run else "written",
            utterplan=context.source_plan_path,
            previous_renderplan=previous_reference,
            previous_render_plan_id=active_id,
            preflight=preflight_path,
            renderplan=child_path,
            render_plan_id=child_id,
            replacement_count=len(preflight.replan),
        )
    except _DocumentReplanProblem as exc:
        problem = exc
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        problem = _DocumentReplanProblem(
            str(exc),
            code="renderplan.replan.bundle.plan_invalid",
            stage=stage,
        )
    return ReplanOutcome(
        index=1,
        id=item.id,
        source_number=1,
        status="failed",
        utterplan=context.source_plan_path,
        previous_renderplan=previous_reference,
        previous_render_plan_id=(active.plan_id or active.computed_id())
        if active is not None
        else None,
        preflight=preflight_path,
        stage=problem.stage,  # type: ignore[arg-type]
        error_code=problem.code,
        error_message=str(problem),
    )


def _find_document_preflight(context: _DocumentContext, active: RenderPlan) -> tuple[Path, Any]:
    item_dir = context.voicerender_dir / context.item.id
    candidates = (item_dir / "preflight-recheck.toml", item_dir / "preflight.toml")
    existing = False
    invalid: list[str] = []
    wrong_status: list[str] = []
    valid: list[tuple[Path, Any]] = []
    active_id = active.plan_id or active.computed_id()
    for path in candidates:
        if not path.is_file():
            continue
        existing = True
        try:
            preflight = renderplan_codec.load_preflight(path)
        except (OSError, ValueError, TypeError) as exc:
            invalid.append(f"{path.name}: {exc}")
            continue
        if preflight.render_plan_id != active_id:
            continue
        try:
            preflight.validate_against(active)
        except (ValueError, TypeError) as exc:
            invalid.append(f"{path.name}: {exc}")
            continue
        if preflight.status != "replan":
            wrong_status.append(f"{path.name} has status={preflight.status!r}")
            continue
        valid.append((path, preflight))
    if valid:
        return valid[0]
    if wrong_status:
        raise _DocumentReplanProblem(
            "matching preflight report is not a replan input: " + "; ".join(wrong_status),
            code="renderplan.replan.bundle.preflight_status",
            stage="preflight",
        )
    if existing:
        detail = "; ".join(invalid)
        message = (
            "available preflight reports belong to an older or invalid RenderPlan; "
            "rerun VoiceRender preflight/render for the currently active plan."
        )
        if detail:
            message += f" Details: {detail}"
        raise _DocumentReplanProblem(
            message,
            code="renderplan.replan.bundle.preflight_stale",
            stage="preflight",
        )
    raise _DocumentReplanProblem(
        f"No preflight report matching active RenderPlan {active_id} was found for {context.item.id}.",
        code="renderplan.replan.bundle.preflight_missing",
        stage="preflight",
    )


def _write_immutable_child(plan: RenderPlan, path: Path) -> None:
    if path.exists():
        try:
            existing = renderplan_codec.load_plan(path)
        except (OSError, ValueError, TypeError) as exc:
            raise _DocumentReplanProblem(
                f"immutable RenderPlan snapshot is invalid: {path}: {exc}",
                code="renderplan.replan.bundle.install_failed",
                stage="write",
            ) from exc
        if existing.plan_id != plan.plan_id:
            raise _DocumentReplanProblem(
                f"refusing to overwrite a different immutable RenderPlan: {path}",
                code="renderplan.replan.bundle.install_failed",
                stage="write",
            )
        return
    try:
        renderplan_codec.save_plan(plan, path)
        persisted = renderplan_codec.load_plan(path)
        if persisted.plan_id != plan.plan_id or persisted != plan:
            raise ValueError("saved immutable RenderPlan does not match the validated plan")
    except (OSError, ValueError, TypeError) as exc:
        raise _DocumentReplanProblem(
            f"could not write immutable RenderPlan snapshot {path}: {exc}",
            code="renderplan.replan.bundle.install_failed",
            stage="write",
        ) from exc


def _replace_active_document_plan(plan: RenderPlan, active_path: Path) -> None:
    if active_path.is_symlink():
        raise _DocumentReplanProblem(
            f"refusing to update active RenderPlan through a symlink: {active_path}",
            code="renderplan.replan.bundle.install_failed",
            stage="write",
        )
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{active_path.name}.", suffix=".tmp", dir=active_path.parent
    )
    os.close(descriptor)
    temporary = Path(temp_name)
    try:
        renderplan_codec.save_plan(plan, temporary)
        persisted = renderplan_codec.load_plan(temporary)
        if persisted.plan_id != plan.plan_id or persisted != plan:
            raise ValueError("temporary active RenderPlan does not match validated child")
        os.replace(temporary, active_path)
    except (OSError, ValueError, TypeError) as exc:
        raise _DocumentReplanProblem(
            f"could not update active document RenderPlan {active_path}: {exc}",
            code="renderplan.replan.bundle.install_failed",
            stage="index",
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def _child_plan_path(active_path: Path, child_id: str) -> Path:
    fingerprint = child_id.removeprefix("sha256:")[:12]
    stem = active_path.name.removesuffix(".renderplan.toml")
    return active_path.with_name(f"{stem}.replan-{fingerprint}.renderplan.toml")


def _parent_snapshot_path(active_path: Path, active_id: str) -> Path:
    fingerprint = active_id.removeprefix("sha256:")[:12]
    stem = active_path.name.removesuffix(".renderplan.toml")
    return active_path.with_name(f"{stem}.replan-parent-{fingerprint}.renderplan.toml")


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


def _write_document_report(
    context: _DocumentContext,
    outcomes: Sequence[ReplanOutcome],
    *,
    dry_run: bool,
    complete: bool,
) -> None:
    items: list[dict[str, Any]] = []
    base = context.report_path.parent
    for outcome in outcomes:
        row: dict[str, Any] = {
            "index": outcome.index,
            "id": outcome.id,
            "source_number": outcome.source_number,
            "status": outcome.status,
            "active_renderplan": _report_path(context.active_path, base),
        }
        for key, value in (
            ("utterplan", outcome.utterplan),
            ("previous_renderplan", outcome.previous_renderplan),
            ("preflight", outcome.preflight),
            ("renderplan", outcome.renderplan),
        ):
            if value is not None:
                row[key] = _report_path(value, base)
        for field_name, field_value in (
            ("previous_render_plan_id", outcome.previous_render_plan_id),
            ("render_plan_id", outcome.render_plan_id),
            ("replacement_count", outcome.replacement_count),
            ("stage", outcome.stage),
            ("code", outcome.error_code),
            ("message", outcome.error_message),
        ):
            if field_value is not None:
                row[field_name] = field_value
        items.append(row)
    data = {
        "format": "utterplan-replan-bundle-report",
        "version": 1,
        "kind": "document",
        "variant": context.variant,
        "selected_item_ids": [context.item.id],
        "requested": 1,
        "written": sum(item.status == "written" for item in outcomes),
        "planned": sum(item.status == "planned" for item in outcomes),
        "failed": sum(item.status == "failed" for item in outcomes),
        "skipped": sum(item.status == "skipped" for item in outcomes),
        "complete": complete,
        "dry_run": dry_run,
        "item": items,
    }
    try:
        atomic_write_text(context.report_path, tomlkit.dumps(data), create_parent=True)
    except OSError as exc:
        raise BundleReplanError(
            f"cannot write bundle replan report {context.report_path}: {exc}",
            code="renderplan.replan.bundle.install_failed",
        ) from exc


def _report_path(path: Path, base: Path) -> str:
    return Path(
        os.path.relpath(path.resolve(strict=False), start=base.resolve(strict=False))
    ).as_posix()


__all__ = [
    "BundleReplanError",
    "BundleReplanResult",
    "BundleReplanStart",
    "BundleReplanStartCallback",
    "replan_bundle",
]
