"""Private orchestration helpers for one-item document bundles."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import tomlkit
from renderplan import codec as renderplan_codec

from .atomic_io import atomic_write_text
from .batch import BatchProgressCallback, CompileOutcome, CompileRequest, compile_to_files
from .config import PlannerConfig
from .model import FlowPlan
from .renderplan_export import build_render_plan
from .renderplan_workspace import profile_fingerprint, render_variant_label
from .renderprofile_io import load_render_profile
from .role_coverage import assert_profile_role_coverage
from .ssmd_bundle import SsmdBundleError, SsmdBundleIndex, bundle_item_path, load_ssmd_bundle
from .workspace_paths import renderplan_output_name, utterplan_output_name


class _DocumentBundleServiceError(ValueError):
    """A document workspace request is invalid or unsafe to execute."""


@dataclass(frozen=True, slots=True)
class DocumentCompileRequest:
    """Options for compiling one editable document bundle."""

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


def _compile_document_service(
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
    bundle_index: SsmdBundleIndex | None = None,
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
        index = bundle_index if bundle_index is not None else load_ssmd_bundle(request.workspace)
        if index.kind != "document":
            raise _DocumentBundleServiceError("bundle manifest format is not a document")
        item = index.items[0]
        source_path = bundle_item_path(index, item, require_exists=True)
    except SsmdBundleError as exc:
        raise _DocumentBundleServiceError(str(exc)) from exc

    output_path = (
        request.output_dir.expanduser()
        if request.output_dir is not None
        else index.root / "utterplan"
    )
    plan_path = output_path / utterplan_output_name(source_path)
    report_path = (
        request.report.expanduser()
        if request.report is not None
        else output_path / "compile-report.toml"
    )
    _preflight_outputs(index.manifest_path, source_path, output_path, plan_path, report_path)

    compile_request = CompileRequest(
        id=item.id,
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
                document_id=item.id,
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
        document_id=item.id,
        source_path=source_path,
        output_dir=output_path,
        plan_path=plan_path,
        report_path=report_path,
        outcome=outcome,
    )


@dataclass(frozen=True, slots=True)
class DocumentRenderStart:
    workspace: Path
    document_id: str
    source_plan_path: Path
    profile_path: Path
    profile_id: str
    variant: str
    variant_dir: Path
    output_path: Path
    report_path: Path
    required_roles: tuple[str, ...] = ()
    available_roles: tuple[str, ...] = ()
    uses_default_role: bool = False


@dataclass(frozen=True, slots=True)
class DocumentRenderResult:
    workspace: Path
    document_id: str
    source_plan_path: Path
    source_plan_id: str
    profile_path: Path
    profile_id: str
    variant: str
    variant_dir: Path
    snapshot_path: Path
    renderplan_path: Path
    render_plan_id: str
    report_path: Path

    required_roles: tuple[str, ...] = ()
    available_roles: tuple[str, ...] = ()
    uses_default_role: bool = False


DocumentRenderStartCallback = Callable[[DocumentRenderStart], None]


def _render_document_service(
    workspace: str | Path,
    *,
    profile: str | Path,
    variant: str | None = None,
    utterplan_dir: str | Path | None = None,
    output_root: str | Path | None = None,
    report: str | Path | None = None,
    force: bool = False,
    on_start: DocumentRenderStartCallback | None = None,
    bundle_index: SsmdBundleIndex | None = None,
) -> DocumentRenderResult:
    """Project the saved document FlowPlan to one profile-specific RenderPlan."""
    try:
        index = bundle_index if bundle_index is not None else load_ssmd_bundle(workspace)
        if index.kind != "document":
            raise _DocumentBundleServiceError("bundle manifest format is not a document")
        item = index.items[0]
        source_path = bundle_item_path(index, item, require_exists=True)
        if variant is not None and (
            "/" in variant or "\\" in variant or "\x00" in variant or variant in {".", ".."}
        ):
            raise _DocumentBundleServiceError(
                "render variant label must not contain path separators or traversal"
            )

        plan_dir = (
            Path(utterplan_dir).expanduser().resolve(strict=False)
            if utterplan_dir is not None
            else index.root / "utterplan"
        )
        source_plan_path = plan_dir / utterplan_output_name(source_path)
        if not source_plan_path.is_file():
            raise _DocumentBundleServiceError(
                f"No UtterPlan found at {source_plan_path}.\n"
                "Run `utterplan bundle compile <workspace>` first."
            )
        source_plan = FlowPlan.load(source_plan_path)

        loaded_profile = load_render_profile(profile)
        profile_path = loaded_profile.path
        active_profile = loaded_profile.profile
        coverage = assert_profile_role_coverage(source_plan, active_profile)
        profile_id = loaded_profile.profile_id
        variant_name = (
            f"{render_variant_label(profile_path, variant)}--{profile_fingerprint(profile_id)}"
        )
        variant_root = (
            Path(output_root).expanduser().resolve(strict=False)
            if output_root is not None
            else index.root / "renderplan"
        )
        variant_dir = variant_root / variant_name
        snapshot_path = variant_dir / "renderprofile.toml"
        renderplan_path = variant_dir / renderplan_output_name(source_path)
        report_path = (
            Path(report).expanduser().resolve(strict=False)
            if report is not None
            else variant_dir / "render-report.toml"
        )

        if variant_root.exists() and not variant_root.is_dir():
            raise _DocumentBundleServiceError(
                f"RenderPlan output root is not a directory: {variant_root}"
            )
        if variant_dir.is_symlink():
            raise _DocumentBundleServiceError(
                f"refusing to write through a variant directory symlink: {variant_dir}"
            )
        if variant_dir.exists() and not variant_dir.is_dir():
            raise _DocumentBundleServiceError(f"variant path is not a directory: {variant_dir}")

        resolved_plan_dir = plan_dir.resolve(strict=False)
        resolved_variant_dir = variant_dir.resolve(strict=False)
        if (
            resolved_variant_dir == resolved_plan_dir
            or resolved_variant_dir in resolved_plan_dir.parents
            or resolved_plan_dir in resolved_variant_dir.parents
        ):
            raise _DocumentBundleServiceError(
                "RenderPlan output must not overlap the UtterPlan input directory"
            )

        output_paths = (renderplan_path, snapshot_path, report_path)
        resolved_outputs = tuple(path.resolve(strict=False) for path in output_paths)
        if len(set(resolved_outputs)) != len(resolved_outputs):
            raise _DocumentBundleServiceError("render output paths collide")
        protected_inputs = {
            index.manifest_path.resolve(strict=True),
            source_path.resolve(strict=True),
            profile_path,
            source_plan_path.resolve(strict=True),
        }
        if any(
            output == protected or protected in output.parents
            for output in resolved_outputs
            for protected in protected_inputs
        ):
            raise _DocumentBundleServiceError("document projection output would overwrite an input")
        for path in output_paths:
            if path.is_symlink():
                raise _DocumentBundleServiceError(f"render output must not be a symlink: {path}")
            if path.exists() and path.is_dir():
                raise _DocumentBundleServiceError(f"metadata output is a directory: {path}")

        has_matching_snapshot = False
        if variant_dir.exists():
            nonempty = next(variant_dir.iterdir(), None) is not None
            if nonempty and not snapshot_path.is_file():
                raise _DocumentBundleServiceError(
                    f"refusing to adopt unknown non-empty variant directory: {variant_dir}"
                )
            if snapshot_path.exists():
                if snapshot_path.is_symlink():
                    raise _DocumentBundleServiceError(
                        f"render profile snapshot must not be a symlink: {snapshot_path}"
                    )
                existing_profile = load_render_profile(snapshot_path)
                existing_id = existing_profile.profile_id
                if existing_id != profile_id:
                    raise _DocumentBundleServiceError(
                        "existing variant snapshot has a different profile identity"
                    )
                has_matching_snapshot = True
            if renderplan_path.exists() and not force:
                raise _DocumentBundleServiceError(
                    f"RenderPlan already exists (use --force): {renderplan_path}"
                )

        plan = build_render_plan(source_plan, active_profile).with_identity()
        if on_start is not None:
            on_start(
                DocumentRenderStart(
                    index.root,
                    item.id,
                    source_plan_path,
                    profile_path,
                    profile_id,
                    variant_name,
                    variant_dir,
                    renderplan_path,
                    report_path,
                    coverage.required_roles,
                    coverage.available_roles,
                    coverage.uses_default_role,
                )
            )

        variant_dir.mkdir(parents=True, exist_ok=True)
        if not has_matching_snapshot:
            renderplan_codec.save_profile(active_profile, snapshot_path)
        renderplan_codec.save_plan(plan, renderplan_path)
        report_data: dict[str, Any] = {
            "format": "utterplan.render-bundle-report",
            "version": 1,
            "status": "ok",
            "workspace": str(index.root.resolve()),
            "document_id": item.id,
            "profile": str(profile_path),
            "profile_id": profile_id,
            "variant": variant_name,
            "source_plan": str(source_plan_path.resolve()),
            "source_plan_id": source_plan.plan_id,
            "render_plan": str(renderplan_path.resolve()),
            "render_plan_id": plan.plan_id,
        }
        atomic_write_text(report_path, tomlkit.dumps(report_data), create_parent=True)
        return DocumentRenderResult(
            index.root,
            item.id,
            source_plan_path,
            source_plan.plan_id,
            profile_path,
            profile_id,
            variant_name,
            variant_dir,
            snapshot_path,
            renderplan_path,
            plan.plan_id,
            report_path,
            coverage.required_roles,
            coverage.available_roles,
            coverage.uses_default_role,
        )
    except (SsmdBundleError, OSError, RuntimeError, ValueError, TypeError) as exc:
        if isinstance(exc, _DocumentBundleServiceError):
            raise
        raise _DocumentBundleServiceError(str(exc)) from exc


def _preflight_outputs(
    manifest_path: Path,
    source_path: Path,
    output_dir: Path,
    plan_path: Path,
    report_path: Path,
) -> None:
    resolved_manifest = manifest_path.resolve(strict=False)
    resolved_source = source_path.resolve(strict=False)
    resolved_output_dir = output_dir.expanduser().resolve(strict=False)
    resolved_plan = plan_path.expanduser().resolve(strict=False)
    resolved_report = report_path.expanduser().resolve(strict=False)
    protected_inputs = (resolved_manifest, resolved_source)

    if resolved_output_dir in protected_inputs or any(
        protected in resolved_output_dir.parents for protected in protected_inputs
    ):
        raise _DocumentBundleServiceError(
            "document output directory overlaps a source workspace file"
        )
    if output_dir.expanduser().exists() and not output_dir.expanduser().is_dir():
        raise _DocumentBundleServiceError(
            f"document output directory is not a directory: {output_dir.expanduser()}"
        )
    if resolved_plan == resolved_report:
        raise _DocumentBundleServiceError(
            f"document report path collides with plan output: {report_path}"
        )
    for output in (resolved_plan, resolved_report):
        if output == resolved_output_dir:
            raise _DocumentBundleServiceError(
                f"document output path collides with output directory: {output}"
            )
        if any(
            output == protected or protected in output.parents for protected in protected_inputs
        ):
            raise _DocumentBundleServiceError(
                f"document output would overwrite source workspace content: {output}"
            )
    for output_path in (plan_path, report_path):
        if output_path.exists() and output_path.is_dir():
            raise _DocumentBundleServiceError(
                f"document output path is a directory when a file is expected: {output_path}"
            )


__all__ = [
    "DocumentCompileRequest",
    "DocumentCompileResult",
    "DocumentCompileStart",
    "DocumentCompileStartCallback",
    "_DocumentBundleServiceError",
    "_compile_document_service",
]
