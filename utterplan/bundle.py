"""Unified compile and render services for manifest-dispatched SSMD bundles."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ._book_service import BookServiceError, compile_book, render_book
from ._document_service import (
    _compile_document_service,
    _DocumentBundleServiceError,
    _render_document_service,
)
from .batch import BatchProgressCallback, CompileOutcome
from .bundle_role_inventory import build_bundle_role_inventory, save_bundle_role_inventory
from .config import PlannerConfig
from .renderplan_batch import RenderOutcome
from .ssmd_bundle import (
    BundleKind,
    SsmdBundleError,
    SsmdBundleIndex,
    bundle_item_path,
    load_ssmd_bundle,
)
from .workspace_paths import renderplan_output_name


class BundleServiceError(ValueError):
    """A bundle service request is invalid or unsafe to execute."""


@dataclass(frozen=True, slots=True)
class BundleCompileStart:
    workspace: Path
    kind: BundleKind
    selector: str
    selected_item_ids: tuple[str, ...]
    output_dir: Path
    report_path: Path


@dataclass(frozen=True, slots=True)
class BundleCompileResult:
    workspace: Path
    kind: BundleKind
    selector: str
    selected_item_ids: tuple[str, ...]
    output_dir: Path
    report_path: Path
    outcomes: tuple[CompileOutcome, ...]

    role_inventory_path: Path | None = None

    @property
    def failed(self) -> int:
        return sum(outcome.status == "failed" for outcome in self.outcomes)

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0


@dataclass(frozen=True, slots=True)
class BundleRenderStart:
    workspace: Path
    kind: BundleKind
    selector: str
    selected_item_ids: tuple[str, ...]
    variant: str
    output_paths: tuple[Path, ...]
    report_path: Path
    required_roles: tuple[str, ...] = ()
    available_roles: tuple[str, ...] = ()
    uses_default_role: bool = False


@dataclass(frozen=True, slots=True)
class BundleRenderResult:
    workspace: Path
    kind: BundleKind
    variant: str
    selected_item_ids: tuple[str, ...]
    outcomes: tuple[RenderOutcome, ...]
    outputs: tuple[Path, ...]
    report_path: Path

    @property
    def output(self) -> tuple[Path, ...]:
        """Return the generated RenderPlan paths for all selected items."""
        return self.outputs

    @property
    def failed(self) -> int:
        return sum(outcome.status == "failed" for outcome in self.outcomes)

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0


BundleCompileStartCallback = Callable[[BundleCompileStart], None]
BundleRenderStartCallback = Callable[[BundleRenderStart], None]


def compile_bundle(
    bundle: str | Path,
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
    on_start: BundleCompileStartCallback | None = None,
) -> BundleCompileResult:
    """Compile a book or document bundle using its manifest-declared kind."""
    index = _load_bundle(bundle)
    selector = chapters.strip()
    if index.kind == "document" and selector != "all":
        raise BundleServiceError("document bundles only support --chapters all")

    if index.kind == "book":
        try:
            book_result = compile_book(
                index.root,
                _index=index,
                chapters=selector,
                output_dir=output_dir,
                report=report,
                language=language,
                planner_config=planner_config,
                force=force,
                fail_fast=fail_fast,
                diagnostics=diagnostics,
                on_progress=on_progress,
                on_start=(
                    lambda start: (
                        on_start(
                            BundleCompileStart(
                                start.workspace,
                                index.kind,
                                selector,
                                start.selected_chapter_ids,
                                start.output_dir,
                                start.report_path,
                            )
                        )
                        if on_start is not None
                        else None
                    )
                ),
            )
        except BookServiceError as exc:
            raise BundleServiceError(str(exc)) from exc
        role_inventory_path = _write_role_inventory(
            index,
            book_result.output_dir,
            book_result.selected_chapter_ids,
            book_result.outcomes,
        )
        return BundleCompileResult(
            workspace=book_result.workspace,
            kind=index.kind,
            selector=book_result.chapter_selector,
            selected_item_ids=book_result.selected_chapter_ids,
            output_dir=book_result.output_dir,
            report_path=book_result.report_path,
            outcomes=book_result.outcomes,
            role_inventory_path=role_inventory_path,
        )

    try:
        document_result = _compile_document_service(
            index.root,
            bundle_index=index,
            output_dir=output_dir,
            report=report,
            language=language,
            planner_config=planner_config,
            force=force,
            diagnostics=diagnostics,
            on_progress=on_progress,
            on_start=(
                lambda start: (
                    on_start(
                        BundleCompileStart(
                            start.workspace,
                            index.kind,
                            selector,
                            (start.document_id,),
                            start.output_dir,
                            start.report_path,
                        )
                    )
                    if on_start is not None
                    else None
                )
            ),
        )
    except _DocumentBundleServiceError as exc:
        raise BundleServiceError(str(exc)) from exc
    role_inventory_path = _write_role_inventory(
        index,
        document_result.output_dir,
        (document_result.document_id,),
        (document_result.outcome,),
    )
    return BundleCompileResult(
        workspace=document_result.workspace,
        kind=index.kind,
        selector=selector,
        selected_item_ids=(document_result.document_id,),
        output_dir=document_result.output_dir,
        report_path=document_result.report_path,
        outcomes=(document_result.outcome,),
        role_inventory_path=role_inventory_path,
    )


def render_bundle(
    bundle: str | Path,
    *,
    profile: str | Path,
    chapters: str = "all",
    variant: str | None = None,
    utterplan_dir: str | Path | None = None,
    output_root: str | Path | None = None,
    report: str | Path | None = None,
    force: bool = False,
    fail_fast: bool = False,
    on_progress: Callable[[RenderOutcome], None] | None = None,
    on_start: BundleRenderStartCallback | None = None,
) -> BundleRenderResult:
    """Project a book or document bundle according to its manifest format."""
    index = _load_bundle(bundle)
    selector = chapters.strip()
    if index.kind == "document" and selector != "all":
        raise BundleServiceError("document bundles only support --chapters all")

    if index.kind == "book":
        try:
            book_result = render_book(
                index.root,
                _index=index,
                profile=profile,
                chapters=selector,
                variant=variant,
                utterplan_dir=utterplan_dir,
                output_root=output_root,
                report=report,
                force=force,
                fail_fast=fail_fast,
                on_progress=on_progress,
                on_start=(
                    lambda start: (
                        on_start(
                            BundleRenderStart(
                                start.workspace,
                                index.kind,
                                selector,
                                start.selected_chapter_ids,
                                start.variant,
                                tuple(
                                    start.variant_dir
                                    / renderplan_output_name(Path(item.relative_path))
                                    for item in index.items
                                    if item.id in start.selected_chapter_ids
                                ),
                                Path(report).expanduser()
                                if report is not None
                                else start.variant_dir / "render-report.toml",
                                start.required_roles,
                                start.available_roles,
                                start.uses_default_role,
                            )
                        )
                        if on_start is not None
                        else None
                    )
                ),
            )
        except BookServiceError as exc:
            raise BundleServiceError(str(exc)) from exc
        return BundleRenderResult(
            workspace=book_result.workspace,
            kind=index.kind,
            variant=book_result.variant,
            selected_item_ids=book_result.selected_chapter_ids,
            outcomes=book_result.outcomes,
            outputs=tuple(outcome.output for outcome in book_result.outcomes),
            report_path=book_result.report_path,
        )

    try:
        document_result = _render_document_service(
            index.root,
            bundle_index=index,
            profile=profile,
            variant=variant,
            utterplan_dir=utterplan_dir,
            output_root=output_root,
            report=report,
            force=force,
            on_start=(
                lambda start: (
                    on_start(
                        BundleRenderStart(
                            start.workspace,
                            index.kind,
                            selector,
                            (start.document_id,),
                            start.variant,
                            (start.output_path,),
                            start.report_path,
                            start.required_roles,
                            start.available_roles,
                            start.uses_default_role,
                        )
                    )
                    if on_start is not None
                    else None
                )
            ),
        )
    except _DocumentBundleServiceError as exc:
        raise BundleServiceError(str(exc)) from exc
    outcome = RenderOutcome(
        id=document_result.document_id,
        source_number=1,
        index=1,
        total=1,
        status="written",
        source_plan=document_result.source_plan_path,
        output=document_result.renderplan_path,
        source_plan_id=document_result.source_plan_id,
        render_plan_id=document_result.render_plan_id,
    )
    return BundleRenderResult(
        workspace=document_result.workspace,
        kind=index.kind,
        variant=document_result.variant,
        selected_item_ids=(document_result.document_id,),
        outcomes=(outcome,),
        outputs=(document_result.renderplan_path,),
        report_path=document_result.report_path,
    )


@dataclass(frozen=True, slots=True)
class _BundleRoleInventoryInput:
    id: str
    source_path: Path
    source_relative_path: str
    plan_path: Path
    plan_relative_path: str


def _write_role_inventory(
    index: SsmdBundleIndex,
    output_dir: Path,
    selected_item_ids: tuple[str, ...],
    outcomes: tuple[CompileOutcome, ...],
) -> Path | None:
    expected_ids = tuple(item.id for item in index.items)
    if selected_item_ids != expected_ids:
        return None
    if len(outcomes) != len(expected_ids) or any(
        outcome.status != "written" for outcome in outcomes
    ):
        return None

    compiled_items: list[_BundleRoleInventoryInput] = []
    bundle_root = index.root.resolve()
    for item, outcome in zip(index.items, outcomes, strict=True):
        if outcome.id != item.id:
            raise BundleServiceError("compile outcome order does not match the bundle manifest")
        source_path = bundle_item_path(index, item, require_exists=True)
        plan_path = Path(outcome.output)
        plan_relative = Path(os.path.relpath(plan_path.resolve(), start=bundle_root)).as_posix()
        compiled_items.append(
            _BundleRoleInventoryInput(
                id=item.id,
                source_path=source_path,
                source_relative_path=item.relative_path,
                plan_path=plan_path,
                plan_relative_path=plan_relative,
            )
        )

    try:
        inventory = build_bundle_role_inventory(
            bundle_root=bundle_root,
            bundle_kind=index.kind,
            manifest_path=index.manifest_path,
            compiled_items=tuple(compiled_items),
        )
        inventory_path = output_dir / "role-inventory.toml"
        save_bundle_role_inventory(inventory, inventory_path)
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        raise BundleServiceError(f"cannot write bundle role inventory: {exc}") from exc
    return inventory_path


def _load_bundle(bundle: str | Path):
    try:
        return load_ssmd_bundle(bundle)
    except SsmdBundleError as exc:
        raise BundleServiceError(str(exc)) from exc


__all__ = [
    "BundleCompileResult",
    "BundleCompileStart",
    "BundleCompileStartCallback",
    "BundleRenderResult",
    "BundleRenderStart",
    "BundleRenderStartCallback",
    "BundleServiceError",
    "compile_bundle",
    "render_bundle",
]
