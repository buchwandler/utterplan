"""Private orchestration helpers for compiling and projecting book bundles.

The services in this module own workspace discovery, chapter selection, artifact
layout, safety checks, variant identity, and batch report handling. They never
write to the console; callers may observe batch outcomes through callbacks.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from renderplan import (
    RenderPlanSet,
    RenderPlanSetError,
    load_renderplan_set,
    save_renderplan_set,
    validate_renderplan_set_profile,
)
from renderplan import codec as renderplan_codec

from .batch import BatchProgressCallback, CompileOutcome, CompileRequest, compile_to_files
from .config import PlannerConfig
from .model import FlowPlan
from .renderplan_batch import RenderOutcome, RenderRequest, new_renderplan_set, render_to_files
from .renderplan_pause_timing import PauseTimingConfig
from .renderplan_workspace import pause_timing_variant_label
from .renderprofile_io import RenderProfileLoadError, load_render_profile
from .role_coverage import profile_role_coverage
from .ssmd_bundle import (
    SsmdBundleError,
    SsmdBundleIndex,
    bundle_item_path,
    load_ssmd_bundle,
    select_bundle_items,
)
from .workspace_paths import renderplan_output_name as _renderplan_output_name
from .workspace_paths import utterplan_output_name as _utterplan_output_name


class BookServiceError(ValueError):
    """A book service request is unsafe or cannot be prepared."""


@dataclass(frozen=True, slots=True)
class BookCompileRequest:
    """Options for compiling selected book bundle chapters to FlowPlans."""

    book: Path
    chapters: str = "all"
    output_dir: Path | None = None
    report: Path | None = None
    language: str | None = None
    force: bool = False
    fail_fast: bool = False
    diagnostics: Literal["errors", "warnings", "all", "none"] = "errors"
    planner_config: PlannerConfig | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "book", Path(self.book))
        if self.output_dir is not None:
            object.__setattr__(self, "output_dir", Path(self.output_dir))
        if self.report is not None:
            object.__setattr__(self, "report", Path(self.report))
        if self.diagnostics not in {"errors", "warnings", "all", "none"}:
            raise ValueError("diagnostics must be 'errors', 'warnings', 'all', or 'none'")


@dataclass(frozen=True, slots=True)
class BookCompileStart:
    """Resolved selection and output locations announced before compilation."""

    workspace: Path
    chapter_selector: str
    selected_chapter_ids: tuple[str, ...]
    output_dir: Path
    report_path: Path


@dataclass(frozen=True, slots=True)
class BookRenderStart:
    """Resolved profile, variant, and output locations announced before projection."""

    workspace: Path
    chapter_selector: str
    profile_path: Path
    profile_id: str
    variant: str
    variant_dir: Path
    utterplan_dir: Path
    selected_chapter_ids: tuple[str, ...]

    required_roles: tuple[str, ...] = ()
    available_roles: tuple[str, ...] = ()
    uses_default_role: bool = False


@dataclass(frozen=True, slots=True)
class BookCompileResult:
    """Artifacts and per-chapter outcomes from a book compilation."""

    workspace: Path
    chapter_selector: str
    selected_chapter_ids: tuple[str, ...]
    output_dir: Path
    report_path: Path
    outcomes: tuple[CompileOutcome, ...]

    @property
    def failed(self) -> int:
        return sum(outcome.status == "failed" for outcome in self.outcomes)

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0


@dataclass(frozen=True, slots=True)
class BookRenderRequest:
    """Options for projecting selected book FlowPlans through a RenderProfile."""

    book: Path
    profile: Path
    chapters: str = "all"
    variant: str | None = None
    utterplan_dir: Path | None = None
    output_root: Path | None = None
    report: Path | None = None
    force: bool = False
    fail_fast: bool = False
    pause_timing: PauseTimingConfig | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "book", Path(self.book))
        object.__setattr__(self, "profile", Path(self.profile))
        if self.utterplan_dir is not None:
            object.__setattr__(self, "utterplan_dir", Path(self.utterplan_dir))
        if self.output_root is not None:
            object.__setattr__(self, "output_root", Path(self.output_root))
        if self.report is not None:
            object.__setattr__(self, "report", Path(self.report))


@dataclass(frozen=True, slots=True)
class BookRenderResult:
    """Artifacts and outcomes from projecting a book into one RenderPlan variant."""

    workspace: Path
    chapter_selector: str
    profile_path: Path
    profile_id: str
    variant: str
    variant_dir: Path
    snapshot_path: Path
    set_path: Path
    report_path: Path
    selected_chapter_ids: tuple[str, ...]
    outcomes: tuple[RenderOutcome, ...]

    @property
    def failed(self) -> int:
        return sum(outcome.status == "failed" for outcome in self.outcomes)

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0


BookCompileStartCallback = Callable[[BookCompileStart], None]
BookRenderStartCallback = Callable[[BookRenderStart], None]
RenderProgressCallback = Callable[[RenderOutcome], None]


def compile_book(
    book: str | Path,
    *,
    chapters: str = "all",
    output_dir: str | Path | None = None,
    report: str | Path | None = None,
    language: str | None = None,
    planner_config: PlannerConfig | None = None,
    force: bool = False,
    fail_fast: bool = False,
    diagnostics: Literal["errors", "warnings", "all", "none"] = "errors",
    on_progress: BatchProgressCallback | None = None,
    on_start: BookCompileStartCallback | None = None,
    _index: SsmdBundleIndex | None = None,
) -> BookCompileResult:
    """Compile selected chapters and atomically write schema-v7 UtterPlans.

    ``on_progress`` receives each batch outcome synchronously. Diagnostics remain
    available on the full outcome regardless of the ``diagnostics`` preference;
    that preference is provided for caller-side presentation policy only.
    """
    request = BookCompileRequest(
        book=Path(book),
        chapters=chapters,
        output_dir=Path(output_dir) if output_dir is not None else None,
        report=Path(report) if report is not None else None,
        language=language,
        force=force,
        fail_fast=fail_fast,
        diagnostics=diagnostics,
        planner_config=planner_config,
    )
    try:
        index = _index if _index is not None else load_ssmd_bundle(request.book)
        if index.kind != "book":
            raise BookServiceError("bundle manifest format is not a book")
        chapters_selected = select_bundle_items(index, request.chapters)
        sources = [bundle_item_path(index, chapter) for chapter in chapters_selected]
    except SsmdBundleError as exc:
        raise BookServiceError(str(exc)) from exc

    output_path = request.output_dir or (index.root / "utterplan")
    chapters_dir = (index.root / "chapters").resolve()
    if _path_is_within(output_path.resolve(), chapters_dir):
        raise BookServiceError("book plan output must not be inside the source chapters/ directory")

    outputs = [output_path / _utterplan_output_name(source) for source in sources]
    owners: dict[Path, Path] = {}
    for source, output in zip(sources, outputs, strict=True):
        key = output.resolve()
        if _path_is_within(key, chapters_dir) or key == index.manifest_path.resolve():
            raise BookServiceError(
                f"book plan output would overwrite source workspace content: {output}"
            )
        if key in owners:
            raise BookServiceError(
                f"selected chapters {owners[key]} and {source} map to the same output {output}"
            )
        owners[key] = source

    report_path = request.report or (output_path / "compile-report.toml")
    resolved_report = report_path.resolve()
    if resolved_report in owners:
        raise BookServiceError(f"book report path collides with plan output: {report_path}")
    if (
        _path_is_within(resolved_report, chapters_dir)
        or resolved_report == index.manifest_path.resolve()
    ):
        raise BookServiceError(
            f"book report path would overwrite source workspace content: {report_path}"
        )

    compile_requests = [
        CompileRequest(
            id=chapter.id,
            source=source,
            output=output,
            input_format="ssmd",
            fallback_language=request.language,
            source_label=str(source),
            require_language=request.language is None,
        )
        for chapter, source, output in zip(chapters_selected, sources, outputs, strict=True)
    ]
    config = request.planner_config or PlannerConfig(language=request.language or "en-US")
    if on_start is not None:
        on_start(
            BookCompileStart(
                workspace=index.root,
                chapter_selector=request.chapters,
                selected_chapter_ids=tuple(chapter.id for chapter in chapters_selected),
                output_dir=output_path,
                report_path=report_path,
            )
        )
    outcomes = tuple(
        compile_to_files(
            compile_requests,
            config=config,
            fail_fast=request.fail_fast,
            force=request.force,
            report_path=report_path,
            on_progress=on_progress,
        )
    )
    return BookCompileResult(
        workspace=index.root,
        chapter_selector=request.chapters,
        selected_chapter_ids=tuple(chapter.id for chapter in chapters_selected),
        output_dir=output_path,
        report_path=report_path,
        outcomes=outcomes,
    )


def render_book(
    book: str | Path,
    *,
    profile: str | Path,
    chapters: str = "all",
    variant: str | None = None,
    pause_timing: PauseTimingConfig | None = None,
    utterplan_dir: str | Path | None = None,
    output_root: str | Path | None = None,
    report: str | Path | None = None,
    force: bool = False,
    fail_fast: bool = False,
    on_progress: RenderProgressCallback | None = None,
    on_start: BookRenderStartCallback | None = None,
    _index: SsmdBundleIndex | None = None,
) -> BookRenderResult:
    """Project selected schema-v7 FlowPlans to a profile-specific RenderPlan set."""
    request = BookRenderRequest(
        book=Path(book),
        profile=Path(profile),
        chapters=chapters,
        variant=variant,
        utterplan_dir=Path(utterplan_dir) if utterplan_dir is not None else None,
        output_root=Path(output_root) if output_root is not None else None,
        report=Path(report) if report is not None else None,
        force=force,
        fail_fast=fail_fast,
        pause_timing=pause_timing,
    )
    timing = request.pause_timing or PauseTimingConfig()
    try:
        index = _index if _index is not None else load_ssmd_bundle(request.book)
        if index.kind != "book":
            raise BookServiceError("bundle manifest format is not a book")
        chapters_selected = select_bundle_items(index, request.chapters)
        sources = [bundle_item_path(index, chapter) for chapter in chapters_selected]
    except SsmdBundleError as exc:
        raise BookServiceError(str(exc)) from exc

    utterplan_dir_arg = request.utterplan_dir or (index.root / "utterplan")
    try:
        utterplan_dir = utterplan_dir_arg.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BookServiceError(
            f"cannot resolve UtterPlan directory {utterplan_dir_arg}: {exc}"
        ) from exc
    if not utterplan_dir.is_dir():
        raise BookServiceError(
            f"UtterPlan directory does not exist or is not a directory: {utterplan_dir}"
        )

    profile_input = request.profile.expanduser()
    try:
        loaded_profile = load_render_profile(profile_input)
    except RenderProfileLoadError as exc:
        raise BookServiceError(str(exc)) from exc
    active_profile = loaded_profile.profile
    profile_path = loaded_profile.path
    profile_id = loaded_profile.profile_id
    fingerprint = profile_id.removeprefix("sha256:")[:12]
    label = pause_timing_variant_label(_render_variant_label(profile_path, request.variant), timing)
    variant_name = f"{label}--{fingerprint}"

    output_root_arg = request.output_root or (index.root / "renderplan")
    output_root = output_root_arg.expanduser().resolve(strict=False)
    variant_dir = (output_root / variant_name).resolve(strict=False)
    snapshot_path = variant_dir / "renderprofile.toml"
    set_path = variant_dir / "renderplan-set.toml"
    report_arg = request.report or (variant_dir / "render-report.toml")
    report_path = report_arg.expanduser().resolve(strict=False)
    chapters_dir = (index.root / "chapters").resolve(strict=False)
    manifest_path = index.manifest_path.resolve(strict=True)

    source_plans = [utterplan_dir / _utterplan_output_name(source) for source in sources]
    outputs = [variant_dir / _renderplan_output_name(source) for source in sources]
    render_requests = [
        RenderRequest(
            id=chapter.id,
            source_number=chapter.source_number,
            source_plan=source_plan,
            output=output,
            source_chapter=source,
        )
        for chapter, source, source_plan, output in zip(
            chapters_selected, sources, source_plans, outputs, strict=True
        )
    ]

    if output_root.exists() and not output_root.is_dir():
        raise BookServiceError(f"RenderPlan output root is not a directory: {output_root}")
    if variant_dir.exists() and not variant_dir.is_dir():
        raise BookServiceError(f"RenderPlan variant path is not a directory: {variant_dir}")
    if _path_is_within(output_root, chapters_dir) or _path_is_within(variant_dir, chapters_dir):
        raise BookServiceError(
            "RenderPlan output root and variant must not be inside source chapters/"
        )
    if _path_is_within(variant_dir, utterplan_dir):
        raise BookServiceError(
            "RenderPlan variant must not be inside the active UtterPlan directory"
        )

    write_paths = [*outputs, snapshot_path, set_path, report_path]
    owners: dict[Path, Path] = {}
    for path in write_paths:
        key = path.resolve(strict=False)
        if key in owners:
            raise BookServiceError(f"RenderPlan output paths collide: {owners[key]} and {path}")
        owners[key] = path
        if _path_is_within(key, chapters_dir):
            raise BookServiceError(f"RenderPlan output would write into source chapters/: {path}")
    if len({path.resolve(strict=False) for path in outputs}) != len(outputs):
        raise BookServiceError("selected chapters map to duplicate RenderPlan output paths")

    input_paths = [manifest_path, profile_path, *source_plans, *sources]
    input_owners = {path.resolve(strict=False): path for path in input_paths}
    for path in write_paths:
        collision = input_owners.get(path.resolve(strict=False))
        if collision is not None:
            raise BookServiceError(f"RenderPlan output path {path} collides with input {collision}")
    for path in (snapshot_path, set_path, report_path):
        if path.exists() and path.is_dir():
            raise BookServiceError(f"RenderPlan metadata output is a directory: {path}")

    if variant_dir.exists():
        if set_path.exists():
            try:
                renderplan_set = load_renderplan_set(set_path)
            except RenderPlanSetError as exc:
                raise BookServiceError(f"invalid existing renderplan-set.toml: {exc}") from exc
            if renderplan_set.variant != label:
                raise BookServiceError(
                    "existing renderplan-set.toml variant does not match its directory"
                )
            if renderplan_set.snapshot != "renderprofile.toml":
                raise BookServiceError(
                    "existing renderplan-set.toml does not use the canonical profile snapshot"
                )
            try:
                validate_renderplan_set_profile(
                    renderplan_set,
                    variant_dir / renderplan_set.snapshot,
                    expected_profile_id=profile_id,
                )
            except RenderPlanSetError as exc:
                raise BookServiceError(str(exc)) from exc
            existing_owners = {
                (variant_dir / chapter.renderplan).resolve(strict=False): chapter.id
                for chapter in renderplan_set.chapters
            }
            for render_request in render_requests:
                owner = existing_owners.get(render_request.output.resolve(strict=False))
                if owner is not None and owner != render_request.id:
                    raise BookServiceError(
                        f"RenderPlan output {render_request.output} is already assigned to chapter {owner}"
                    )
        else:
            try:
                nonempty = next(variant_dir.iterdir(), None) is not None
            except OSError as exc:
                raise BookServiceError(
                    f"cannot inspect RenderPlan variant {variant_dir}: {exc}"
                ) from exc
            if nonempty:
                raise BookServiceError(
                    "refusing to adopt non-empty RenderPlan variant without a valid set index: "
                    f"{variant_dir}"
                )
            renderplan_set = _new_book_renderplan_set(
                label,
                profile_id,
                profile_path,
                index.root,
                utterplan_dir,
                variant_dir,
                manifest_path,
            )
    else:
        renderplan_set = _new_book_renderplan_set(
            label, profile_id, profile_path, index.root, utterplan_dir, variant_dir, manifest_path
        )

    # Validate readable source plans and aggregate role coverage before creating collection state.
    required_roles_in_order: list[str] = []
    missing_roles_by_chapter: dict[str, list[str]] = {}
    uses_default_role = False
    for chapter, source_plan_path in zip(chapters_selected, source_plans, strict=True):
        if source_plan_path.is_file():
            source_plan = FlowPlan.load(source_plan_path)
            coverage = profile_role_coverage(source_plan, active_profile)
            uses_default_role = uses_default_role or coverage.uses_default_role
            for role in coverage.required_roles:
                if role not in required_roles_in_order:
                    required_roles_in_order.append(role)
            for role in coverage.missing_roles:
                missing_roles_by_chapter.setdefault(role, []).append(chapter.id)
    if missing_roles_by_chapter:
        details = "\n".join(
            f"  {role}: {', '.join(chapter_ids)}"
            for role, chapter_ids in missing_roles_by_chapter.items()
        )
        raise BookServiceError("RenderProfile does not cover selected book roles:\n" + details)
    required_roles = tuple(required_roles_in_order)
    available_roles = tuple(sorted(active_profile.roles))
    if not variant_dir.exists():
        try:
            variant_dir.mkdir(parents=True)
        except OSError as exc:
            raise BookServiceError(
                f"cannot create RenderPlan variant directory {variant_dir}: {exc}"
            ) from exc
    if not set_path.exists():
        try:
            renderplan_codec.save_profile(active_profile, snapshot_path)
            save_renderplan_set(set_path, renderplan_set)
        except (OSError, ValueError, TypeError) as exc:
            raise BookServiceError(
                f"cannot initialize RenderPlan variant {variant_dir}: {exc}"
            ) from exc

    if on_start is not None:
        on_start(
            BookRenderStart(
                workspace=index.root,
                chapter_selector=request.chapters,
                profile_path=profile_path,
                profile_id=profile_id,
                variant=variant_name,
                variant_dir=variant_dir,
                utterplan_dir=utterplan_dir,
                selected_chapter_ids=tuple(chapter.id for chapter in chapters_selected),
                required_roles=required_roles,
                available_roles=available_roles,
                uses_default_role=uses_default_role,
            )
        )

    try:
        outcomes = tuple(
            render_to_files(
                render_requests,
                profile=active_profile,
                renderplan_set=renderplan_set,
                pause_timing=timing,
                set_path=set_path,
                report_path=report_path,
                force=request.force,
                fail_fast=request.fail_fast,
                chapter_order={chapter.id: order for order, chapter in enumerate(index.items)},
                on_progress=on_progress,
            )
        )
    except RenderPlanSetError as exc:
        raise BookServiceError(str(exc)) from exc

    return BookRenderResult(
        workspace=index.root,
        chapter_selector=request.chapters,
        profile_path=profile_path,
        profile_id=profile_id,
        variant=variant_name,
        variant_dir=variant_dir,
        snapshot_path=snapshot_path,
        set_path=set_path,
        report_path=report_path,
        selected_chapter_ids=tuple(chapter.id for chapter in chapters_selected),
        outcomes=outcomes,
    )


def _new_book_renderplan_set(
    label: str,
    profile_id: str,
    profile_path: Path,
    book_root: Path,
    utterplan_dir: Path,
    variant_dir: Path,
    manifest_path: Path,
) -> RenderPlanSet:
    profile_in_workspace = _path_is_within(profile_path, book_root) or _path_is_within(
        profile_path, variant_dir.parent
    )
    profile_reference = (
        _relative_path_reference(profile_path, variant_dir)
        if profile_in_workspace
        else str(profile_path)
    )
    return new_renderplan_set(
        variant=label,
        profile_id=profile_id,
        manifest=_relative_path_reference(manifest_path, variant_dir),
        utterplan_dir=_relative_path_reference(utterplan_dir, variant_dir),
        source_profile=profile_reference,
    )


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _relative_path_reference(path: Path, base: Path) -> str:
    return Path(
        os.path.relpath(path.resolve(strict=False), start=base.resolve(strict=False))
    ).as_posix()


def _render_variant_label(profile_path: Path, override: str | None) -> str:
    from .renderplan_workspace import render_variant_label

    return render_variant_label(profile_path, override)


__all__ = [
    "BookCompileRequest",
    "BookCompileResult",
    "BookRenderRequest",
    "BookRenderResult",
    "BookCompileStart",
    "BookCompileStartCallback",
    "BookRenderStart",
    "BookRenderStartCallback",
    "BookServiceError",
    "RenderProgressCallback",
    "compile_book",
    "render_book",
]
