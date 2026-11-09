"""Read-only bundle freshness inspectors for workflow-level convergence."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from renderplan import RenderPlanSetError, load_renderplan_set, validate_renderplan_set_profile
from renderplan import codec as renderplan_codec

from .config import PlannerConfig, semantic_config_fingerprint
from .exceptions import UtterPlanError
from .model import FlowPlan
from .renderplan_pause_timing import PauseTimingConfig
from .renderplan_workspace import (
    pause_timing_variant_label,
    profile_fingerprint,
    render_variant_label,
)
from .renderprofile_io import load_render_profile
from .role_coverage import assert_profile_role_coverage
from .ssmd_bundle import (
    BundleItem,
    BundleKind,
    SsmdBundleError,
    SsmdBundleIndex,
    bundle_item_path,
    load_ssmd_bundle,
    select_bundle_items,
)
from .workspace_paths import renderplan_output_name, utterplan_output_name

CompileItemState = Literal["not_started", "complete", "stale", "error"]
CompileState = Literal["not_started", "partial", "complete", "stale", "error"]
ProjectionItemState = Literal["missing", "complete", "stale", "not_ready", "error"]
ProjectionState = Literal[
    "not_started", "partial", "complete", "stale", "blocked", "profile_mismatch", "error"
]


class BundleInspectionError(ValueError):
    """A read-only bundle inspection request cannot be resolved safely."""


@dataclass(frozen=True, slots=True)
class BundleCompileItemInspection:
    id: str
    source_number: int
    title: str | None
    source_path: Path
    plan_path: Path
    state: CompileItemState
    plan_id: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BundleCompileInspection:
    workspace: Path
    kind: BundleKind
    selector: str
    items: tuple[BundleCompileItemInspection, ...]
    state: CompileState
    recommended_selector: str | None
    force_required: bool

    replacement_safe: bool = False

    @property
    def selected_item_ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self.items)


@dataclass(frozen=True, slots=True)
class BundleProjectionItemInspection:
    id: str
    source_number: int
    title: str | None
    source_plan_path: Path
    renderplan_path: Path
    state: ProjectionItemState
    source_plan_id: str | None = None
    render_plan_id: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BundleProjectionInspection:
    workspace: Path
    kind: BundleKind
    selector: str
    variant: str
    profile_id: str
    items: tuple[BundleProjectionItemInspection, ...]
    chapters_in_set: tuple[str, ...]
    missing_chapters: tuple[str, ...]
    stale_chapters: tuple[str, ...]
    profile_snapshot_mismatch: bool
    state: ProjectionState
    recommended_selector: str | None
    force_required: bool
    replacement_safe: bool = False

    @property
    def selected_item_ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self.items)


def inspect_bundle_compile(
    bundle: str | Path,
    *,
    chapters: str = "all",
    language: str | None = None,
    planner_config: PlannerConfig | None = None,
    output_dir: str | Path | None = None,
) -> BundleCompileInspection:
    """Inspect selected FlowPlans by exact source and optional planner-config identity."""
    index = _load_index(bundle)
    selected = _select_items(index, chapters)
    output_path = (
        Path(output_dir).expanduser().resolve(strict=False)
        if output_dir is not None
        else index.root / "utterplan"
    )
    config = planner_config or PlannerConfig(language=language or "en-US")
    if language is not None:
        config = replace(config, language=language)
    config = replace(config, document_format="ssmd")
    expected_config_id = semantic_config_fingerprint(config)

    inspected: list[BundleCompileItemInspection] = []
    for item in selected:
        try:
            source_path = bundle_item_path(index, item, require_exists=True)
            plan_path = output_path / utterplan_output_name(source_path)
            source_text = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError, SsmdBundleError, ValueError) as exc:
            inspected.append(_compile_item(item, index.root, output_path, "error", error=str(exc)))
            continue

        if plan_path.is_symlink() or (plan_path.exists() and not plan_path.is_file()):
            inspected.append(
                BundleCompileItemInspection(
                    item.id,
                    item.source_number,
                    item.title,
                    source_path,
                    plan_path,
                    "error",
                    error=f"UtterPlan output is not a regular file: {plan_path}",
                )
            )
            continue
        if not plan_path.exists():
            inspected.append(
                BundleCompileItemInspection(
                    item.id, item.source_number, item.title, source_path, plan_path, "not_started"
                )
            )
            continue
        try:
            plan = FlowPlan.load(plan_path)
        except (OSError, UtterPlanError, ValueError, TypeError, RuntimeError) as exc:
            inspected.append(
                BundleCompileItemInspection(
                    item.id,
                    item.source_number,
                    item.title,
                    source_path,
                    plan_path,
                    "error",
                    error=f"cannot load UtterPlan {plan_path}: {exc}",
                )
            )
            continue

        current = (
            plan.source is not None
            and plan.source.format == "ssmd"
            and plan.source.text == source_text
        )
        if expected_config_id is not None:
            current = current and (plan.producer.get("planner_config_sha256") == expected_config_id)
        state: CompileItemState = "complete" if current else "stale"
        inspected.append(
            BundleCompileItemInspection(
                item.id,
                item.source_number,
                item.title,
                source_path,
                plan_path,
                state,
                plan_id=plan.plan_id,
            )
        )

    items = tuple(inspected)
    work = tuple(item for item in items if item.state in {"not_started", "stale"})
    return BundleCompileInspection(
        workspace=index.root,
        kind=index.kind,
        selector=chapters.strip(),
        items=items,
        state=_compile_aggregate(items),
        recommended_selector=_selector_for(index, tuple(item.id for item in work)),
        force_required=any(item.state == "stale" for item in items),
        replacement_safe=all(item.state != "error" for item in items),
    )


def inspect_bundle_projection(
    bundle: str | Path,
    *,
    profile: str | Path,
    chapters: str = "all",
    variant: str | None = None,
    pause_timing: PauseTimingConfig | None = None,
    utterplan_dir: str | Path | None = None,
    output_root: str | Path | None = None,
) -> BundleProjectionInspection:
    """Inspect selected RenderPlans and profile identity without creating workspace files."""
    index = _load_index(bundle)
    selected = _select_items(index, chapters)
    if variant is not None and (
        "/" in variant or "\\" in variant or "\x00" in variant or variant in {".", ".."}
    ):
        raise BundleInspectionError(
            "render variant label must not contain path separators or traversal"
        )
    try:
        loaded_profile = load_render_profile(profile)
    except (OSError, UtterPlanError, ValueError, TypeError, RuntimeError) as exc:
        raise BundleInspectionError(f"cannot load RenderProfile: {exc}") from exc

    profile_path = loaded_profile.path
    profile_id = loaded_profile.profile_id
    timing = pause_timing or PauseTimingConfig()
    label = pause_timing_variant_label(render_variant_label(profile_path, variant), timing)
    variant = f"{label}--{profile_fingerprint(profile_id)}"
    plan_dir = (
        Path(utterplan_dir).expanduser().resolve(strict=False)
        if utterplan_dir is not None
        else index.root / "utterplan"
    )
    variant_root = (
        Path(output_root).expanduser().resolve(strict=False)
        if output_root is not None
        else index.root / "renderplan"
    )
    variant_dir = variant_root / variant
    snapshot_path = variant_dir / "renderprofile.toml"
    set_path = variant_dir / "renderplan-set.toml"
    set_value = None
    profile_mismatch = False
    global_error: str | None = None

    try:
        if variant_dir.is_symlink():
            raise BundleInspectionError(
                f"refusing to inspect through a variant directory symlink: {variant_dir}"
            )
        if variant_dir.exists() and not variant_dir.is_dir():
            raise BundleInspectionError(
                f"RenderPlan variant path is not a directory: {variant_dir}"
            )
        if _within(variant_dir, index.root / "chapters") or _within(variant_dir, plan_dir):
            raise BundleInspectionError(
                "RenderPlan variant overlaps source chapters or UtterPlan inputs"
            )
        if index.kind == "book" and set_path.exists():
            if set_path.is_symlink() or not set_path.is_file():
                raise BundleInspectionError(f"RenderPlan set is not a regular file: {set_path}")
            set_value = load_renderplan_set(set_path)
            if set_value.variant != label:
                raise BundleInspectionError(
                    "existing RenderPlan set variant does not match its directory"
                )
            if set_value.snapshot != "renderprofile.toml":
                raise BundleInspectionError(
                    "existing RenderPlan set does not use the canonical profile snapshot"
                )
            if set_value.profile_id != profile_id:
                profile_mismatch = True
            try:
                validate_renderplan_set_profile(
                    set_value, snapshot_path, expected_profile_id=profile_id
                )
            except RenderPlanSetError:
                profile_mismatch = True
        elif index.kind == "book" and variant_dir.exists():
            if next(variant_dir.iterdir(), None) is not None:
                raise BundleInspectionError(
                    f"refusing to inspect non-empty RenderPlan variant without a set index: {variant_dir}"
                )
        elif index.kind == "document" and snapshot_path.exists():
            if snapshot_path.is_symlink() or not snapshot_path.is_file():
                profile_mismatch = True
                raise BundleInspectionError(
                    f"RenderProfile snapshot is not a regular file: {snapshot_path}"
                )
            try:
                snapshot = load_render_profile(snapshot_path)
            except (OSError, UtterPlanError, ValueError, TypeError, RuntimeError) as exc:
                profile_mismatch = True
                raise BundleInspectionError(f"invalid RenderProfile snapshot: {exc}") from exc
            profile_mismatch = snapshot.profile_id != profile_id
        elif (
            index.kind == "document"
            and variant_dir.exists()
            and next(variant_dir.iterdir(), None) is not None
            and not snapshot_path.is_file()
        ):
            raise BundleInspectionError(
                f"refusing to inspect non-empty RenderPlan variant without a profile snapshot: {variant_dir}"
            )
    except BundleInspectionError as exc:
        global_error = str(exc)
    except (OSError, RenderPlanSetError, ValueError, TypeError, RuntimeError) as exc:
        global_error = f"cannot inspect RenderPlan variant {variant_dir}: {exc}"

    set_entries = {entry.id: entry for entry in set_value.chapters} if set_value is not None else {}
    owners = (
        {
            (variant_dir / entry.renderplan).resolve(strict=False): entry.id
            for entry in set_value.chapters
        }
        if set_value is not None
        else {}
    )
    inspected: list[BundleProjectionItemInspection] = []
    for item in selected:
        try:
            source_path = bundle_item_path(index, item, require_exists=True)
            source_plan_path = plan_dir / utterplan_output_name(source_path)
            renderplan_path = variant_dir / renderplan_output_name(source_path)
        except (OSError, SsmdBundleError, ValueError) as exc:
            inspected.append(
                _projection_item(item, index.root, plan_dir, variant_dir, "error", error=str(exc))
            )
            continue

        if global_error is not None:
            inspected.append(
                BundleProjectionItemInspection(
                    item.id,
                    item.source_number,
                    item.title,
                    source_plan_path,
                    renderplan_path,
                    "error",
                    error=global_error,
                )
            )
            continue
        if profile_mismatch:
            inspected.append(
                BundleProjectionItemInspection(
                    item.id,
                    item.source_number,
                    item.title,
                    source_plan_path,
                    renderplan_path,
                    "error",
                    error="RenderProfile snapshot identity does not match the requested profile",
                )
            )
            continue
        if source_plan_path.is_symlink() or (
            source_plan_path.exists() and not source_plan_path.is_file()
        ):
            inspected.append(
                BundleProjectionItemInspection(
                    item.id,
                    item.source_number,
                    item.title,
                    source_plan_path,
                    renderplan_path,
                    "error",
                    error=f"UtterPlan input is not a regular file: {source_plan_path}",
                )
            )
            continue
        if not source_plan_path.is_file():
            inspected.append(
                BundleProjectionItemInspection(
                    item.id,
                    item.source_number,
                    item.title,
                    source_plan_path,
                    renderplan_path,
                    "not_ready",
                    error="UtterPlan has not been compiled",
                )
            )
            continue
        try:
            source_plan = FlowPlan.load(source_plan_path)
            assert_profile_role_coverage(source_plan, loaded_profile.profile)
        except (OSError, UtterPlanError, ValueError, TypeError, RuntimeError) as exc:
            inspected.append(
                BundleProjectionItemInspection(
                    item.id,
                    item.source_number,
                    item.title,
                    source_plan_path,
                    renderplan_path,
                    "error",
                    error=f"cannot use UtterPlan for projection: {exc}",
                )
            )
            continue

        entry = set_entries.get(item.id) if index.kind == "book" else None
        if index.kind == "book":
            owner = owners.get(renderplan_path.resolve(strict=False))
            if owner is not None and owner != item.id:
                inspected.append(
                    BundleProjectionItemInspection(
                        item.id,
                        item.source_number,
                        item.title,
                        source_plan_path,
                        renderplan_path,
                        "error",
                        source_plan_id=source_plan.plan_id,
                        error=f"RenderPlan output is already assigned to chapter {owner}",
                    )
                )
                continue

        if renderplan_path.is_symlink() or (
            renderplan_path.exists() and not renderplan_path.is_file()
        ):
            inspected.append(
                BundleProjectionItemInspection(
                    item.id,
                    item.source_number,
                    item.title,
                    source_plan_path,
                    renderplan_path,
                    "error",
                    source_plan_id=source_plan.plan_id,
                    error=f"RenderPlan output is not a regular file: {renderplan_path}",
                )
            )
            continue

        current = False
        render_plan_id: str | None = None
        stale_reason: str | None = None
        if index.kind == "book":
            if entry is None:
                if renderplan_path.exists():
                    current = False
                    stale_reason = "unindexed RenderPlan output already exists"
                else:
                    inspected.append(
                        BundleProjectionItemInspection(
                            item.id,
                            item.source_number,
                            item.title,
                            source_plan_path,
                            renderplan_path,
                            "missing",
                            source_plan_id=source_plan.plan_id,
                        )
                    )
                    continue
            else:
                if entry.source_plan_id != source_plan.plan_id:
                    stale_reason = "source plan identity changed"
                elif entry.renderplan != renderplan_path.name:
                    stale_reason = "RenderPlan set output path does not match this item"
                elif not renderplan_path.is_file():
                    stale_reason = "indexed RenderPlan output is missing"
                else:
                    try:
                        projected = renderplan_codec.load_plan(renderplan_path)
                        render_plan_id = projected.plan_id
                        projected.validate_against_profile(loaded_profile.profile)
                        current = (
                            projected.plan_id == entry.render_plan_id
                            and projected.source_plan_id == source_plan.plan_id
                            and projected.render_profile_id == profile_id
                        )
                        if not current:
                            stale_reason = (
                                "RenderPlan identity does not match its set entry or current inputs"
                            )
                    except (OSError, UtterPlanError, ValueError, TypeError, RuntimeError) as exc:
                        stale_reason = f"cannot load indexed RenderPlan: {exc}"
        else:
            if not renderplan_path.exists():
                inspected.append(
                    BundleProjectionItemInspection(
                        item.id,
                        item.source_number,
                        item.title,
                        source_plan_path,
                        renderplan_path,
                        "missing",
                        source_plan_id=source_plan.plan_id,
                    )
                )
                continue
            try:
                projected = renderplan_codec.load_plan(renderplan_path)
                render_plan_id = projected.plan_id
                projected.validate_against_profile(loaded_profile.profile)
                current = (
                    projected.source_plan_id == source_plan.plan_id
                    and projected.render_profile_id == profile_id
                )
                if not current:
                    stale_reason = "RenderPlan identity does not match current inputs"
            except (OSError, UtterPlanError, ValueError, TypeError, RuntimeError) as exc:
                stale_reason = f"cannot load RenderPlan: {exc}"

        state: ProjectionItemState = "complete" if current else "stale"
        inspected.append(
            BundleProjectionItemInspection(
                item.id,
                item.source_number,
                item.title,
                source_plan_path,
                renderplan_path,
                state,
                source_plan_id=source_plan.plan_id,
                render_plan_id=render_plan_id,
                error=stale_reason,
            )
        )

    items = tuple(inspected)
    work = tuple(item for item in items if item.state in {"missing", "stale"})
    if profile_mismatch or global_error is not None:
        work = ()
    force_required = any(
        item.state == "stale" or (item.state == "missing" and item.renderplan_path.exists())
        for item in work
    )
    return BundleProjectionInspection(
        workspace=index.root,
        kind=index.kind,
        selector=chapters.strip(),
        variant=variant,
        profile_id=profile_id,
        items=items,
        chapters_in_set=tuple(item.id for item in items if item.id in set_entries),
        missing_chapters=tuple(item.id for item in items if item.state == "missing"),
        stale_chapters=tuple(item.id for item in items if item.state == "stale"),
        profile_snapshot_mismatch=profile_mismatch,
        state=_projection_aggregate(items, profile_mismatch, global_error),
        recommended_selector=_selector_for(index, tuple(item.id for item in work)),
        force_required=force_required,
        replacement_safe=not profile_mismatch
        and global_error is None
        and all(item.state not in {"error", "not_ready"} for item in items),
    )


def _load_index(bundle: str | Path) -> SsmdBundleIndex:
    try:
        return load_ssmd_bundle(bundle)
    except (SsmdBundleError, OSError, ValueError, TypeError) as exc:
        raise BundleInspectionError(str(exc)) from exc


def _select_items(index: SsmdBundleIndex, selector: str) -> tuple[BundleItem, ...]:
    try:
        return select_bundle_items(index, selector)
    except SsmdBundleError as exc:
        raise BundleInspectionError(str(exc)) from exc


def _compile_item(
    item: BundleItem,
    root: Path,
    output_dir: Path,
    state: CompileItemState,
    *,
    error: str | None = None,
) -> BundleCompileItemInspection:
    source = root / item.relative_path
    return BundleCompileItemInspection(
        item.id,
        item.source_number,
        item.title,
        source,
        output_dir / utterplan_output_name(source),
        state,
        error=error,
    )


def _projection_item(
    item: BundleItem,
    root: Path,
    plan_dir: Path,
    variant_dir: Path,
    state: ProjectionItemState,
    *,
    error: str | None = None,
) -> BundleProjectionItemInspection:
    source = root / item.relative_path
    return BundleProjectionItemInspection(
        item.id,
        item.source_number,
        item.title,
        plan_dir / utterplan_output_name(source),
        variant_dir / renderplan_output_name(source),
        state,
        error=error,
    )


def _compile_aggregate(items: tuple[BundleCompileItemInspection, ...]) -> CompileState:
    states = {item.state for item in items}
    if "error" in states:
        return "error"
    if "stale" in states:
        return "stale"
    if states == {"complete"}:
        return "complete"
    if states == {"not_started"}:
        return "not_started"
    return "partial"


def _projection_aggregate(
    items: tuple[BundleProjectionItemInspection, ...],
    profile_mismatch: bool,
    global_error: str | None,
) -> ProjectionState:
    if profile_mismatch:
        return "profile_mismatch"
    if global_error is not None or any(item.state == "error" for item in items):
        return "error"
    states = {item.state for item in items}
    if "not_ready" in states:
        return "blocked"
    if "stale" in states:
        return "stale"
    if states == {"complete"}:
        return "complete"
    if states == {"missing"}:
        return "not_started"
    return "partial"


def _selector_for(index: SsmdBundleIndex, item_ids: tuple[str, ...]) -> str | None:
    if not item_ids:
        return None
    if index.kind == "document":
        return "all"
    by_id = {item.id: item.source_number for item in index.items}
    numbers = sorted(by_id[item_id] for item_id in item_ids)
    ranges: list[str] = []
    first = last = numbers[0]
    for number in numbers[1:]:
        if number == last + 1:
            last = number
            continue
        ranges.append(str(first) if first == last else f"{first}-{last}")
        first = last = number
    ranges.append(str(first) if first == last else f"{first}-{last}")
    return ",".join(ranges)


def _within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True


__all__ = [
    "BundleCompileInspection",
    "BundleCompileItemInspection",
    "BundleInspectionError",
    "BundleProjectionInspection",
    "BundleProjectionItemInspection",
    "inspect_bundle_compile",
    "inspect_bundle_projection",
]
