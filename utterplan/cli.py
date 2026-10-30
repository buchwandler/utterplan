from __future__ import annotations

import argparse
import json
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal, cast

import tomlkit
from renderplan import codec as renderplan_codec
from tomlkit.exceptions import ParseError

from . import __version__
from .atomic_io import atomic_write_text
from .attempts import PlanningAttempt
from .batch import CompileOutcome, CompileRequest, compile_to_files
from .bundle import (
    BundleCompileStart,
    BundleRenderStart,
    BundleServiceError,
)
from .bundle import (
    compile_bundle as _compile_bundle_service,
)
from .bundle import (
    render_bundle as _render_bundle_service,
)
from .bundle_replan import (
    BundleReplanError,
    BundleReplanStart,
    ReplanOutcome,
)
from .bundle_replan import (
    replan_bundle as _replan_bundle_service,
)
from .bundle_role_inventory import load_bundle_role_inventory
from .compiler import InputFormat, PreparationTrace, compile_document
from .config import LinguisticsConfig, PlannerConfig
from .exceptions import PlanFormatError, PlanRenderabilityError, UtterPlanError
from .explain import format_explanation
from .migration import MigrationResult, migrate_plan_data
from .model import FlowPlan, PauseIntent
from .preview import PreviewChunk, preview_plan
from .renderability import format_renderability_error
from .renderplan_batch import RenderOutcome
from .renderplan_export import build_render_plan, format_render_plan_explanation
from .renderplan_pause_timing import (
    PAUSE_TIMING_ALGORITHM,
    PauseTimingConfig,
    PauseTimingMode,
)
from .renderprofile_io import load_render_profile
from .role_coverage import logical_role_inventory, profile_role_coverage
from .source_input import _format_for_path as _format_source_path
from .source_input import load_source_path
from .trace_codec import loads_trace
from .versioning import CURRENT_SCHEMA_VERSION, V5_SCHEMA_VERSION, V6_SCHEMA_VERSION
from .workspace_paths import utterplan_output_name as _utterplan_output_name

_EXAMPLES = """examples:
  utterplan compile chapter.ssmd.md
  utterplan compile plain.txt --input-format plain --language de-DE --stdout
  utterplan compile-many chapters/*.ssmd --output-dir build/plans
  utterplan bundle compile novel.ssmd-bundle --chapters 5-17
  utterplan bundle render novel.ssmd-bundle --profile narration.renderprofile.toml
  utterplan bundle replan novel.ssmd-bundle --variant narration--28f616b6fe3b
  utterplan validate chapter.utterplan.toml
  utterplan preview chapter.utterplan.toml --chunk-by sentence --pause-policy native
  utterplan render-plan chapter.utterplan.toml --profile voice.renderprofile.toml -o chapter.renderplan.toml
  utterplan inspect chapter.utterplan.toml --segment 0
  utterplan inspect-attempt attempt.toml --issues
  utterplan explain chapter.utterplan.toml
  utterplan migrate old.utterplan.json -o old.utterplan.toml
"""


class _CliUsageError(Exception):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="utterplan",
        description="Compile text or SSMD into deterministic, engine-independent TTS plans.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_EXAMPLES,
    )
    parser.add_argument("--version", action="version", version=f"utterplan {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    compile_parser = commands.add_parser(
        "compile",
        help="compile literal text, stdin, or a file into a TTS plan",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_EXAMPLES,
    )
    compile_parser.add_argument(
        "text",
        nargs="*",
        help="literal text, or one existing file path; omit to read stdin",
    )
    compile_parser.add_argument(
        "--file",
        type=Path,
        help="read UTF-8 text from this file (cannot be combined with positional text)",
    )
    compile_parser.add_argument(
        "--language",
        "--lang",
        dest="language",
        help="fallback language when SSMD does not declare one (required for plain input)",
    )
    compile_parser.add_argument(
        "--input-format",
        "--format",
        dest="input_format",
        choices=("auto", "text", "plain", "ssmd"),
        default="auto",
        help="input interpretation; auto detects .ssmd, .ssmd.md, and Markdown with SSMD version front matter",
    )
    compile_parser.add_argument(
        "--text-preparation",
        choices=("auto", "ssmd", "spokenform", "identity"),
        default="auto",
    )
    compile_parser.add_argument(
        "--renderability",
        choices=("strict", "repair"),
        default="repair",
        help="safely repair isolated punctuation by default; strict rejects every repair opportunity",
    )
    compile_parser.add_argument(
        "--spacy",
        choices=("auto", "off", "sm", "md", "lg", "trf"),
        default="auto",
        help="linguistic-resource policy; default auto uses a compatible local spaCy model when available and falls back safely",
    )
    compile_parser.add_argument("-o", "--output", type=Path, help="write the plan to this file")
    compile_parser.add_argument(
        "--trace", type=Path, help="write compiler provenance to this optional trace sidecar"
    )
    compile_parser.add_argument(
        "--force", action="store_true", help="replace an existing output file"
    )
    compile_parser.add_argument(
        "--stdout",
        action="store_true",
        help="also print the TOML plan when --output is used",
    )

    batch_parser = commands.add_parser(
        "compile-many",
        help="compile independent source files into one TOML plan per file",
    )
    batch_parser.add_argument(
        "inputs", nargs="+", type=Path, help="source files in processing order"
    )
    batch_parser.add_argument("--output-dir", type=Path, required=True)
    batch_parser.add_argument("--language", "--lang", dest="language")
    batch_parser.add_argument("--input-format", choices=("auto", "plain", "ssmd"), default="auto")
    batch_parser.add_argument(
        "--text-preparation", choices=("auto", "ssmd", "spokenform", "identity"), default="auto"
    )
    batch_parser.add_argument(
        "--renderability",
        choices=("strict", "repair"),
        default="repair",
        help="safely repair isolated punctuation by default; strict rejects every repair opportunity",
    )
    batch_parser.add_argument(
        "--spacy",
        choices=("auto", "off", "sm", "md", "lg", "trf"),
        default="auto",
        help="linguistic-resource policy; default auto uses a compatible local spaCy model when available and falls back safely",
    )
    batch_parser.add_argument("--force", action="store_true", help="replace existing plan files")
    batch_parser.add_argument(
        "--fail-fast", action="store_true", help="skip remaining inputs after the first failure"
    )
    batch_parser.add_argument("--report", type=Path, help="TOML operational report path")

    batch_parser.add_argument(
        "--diagnostics",
        choices=("warnings", "all", "none"),
        default="warnings",
        help="diagnostic detail verbosity (default: warnings)",
    )
    bundle_parser = commands.add_parser(
        "bundle",
        help="compile, render, or replan a manifest-dispatched SSMD bundle",
    )
    bundle_commands = bundle_parser.add_subparsers(dest="bundle_command", required=True)

    bundle_compile = bundle_commands.add_parser("compile", help="compile a book or document bundle")
    bundle_compile.add_argument(
        "workspace", type=Path, help="path resolving to a canonical NAME.ssmd-bundle directory"
    )
    bundle_compile.add_argument("--chapters", default="all", metavar="SELECTOR")
    bundle_compile.add_argument("--output-dir", type=Path)
    bundle_compile.add_argument("--language", "--lang", dest="language")
    bundle_compile.add_argument(
        "--text-preparation", choices=("auto", "ssmd", "spokenform", "identity"), default="auto"
    )
    bundle_compile.add_argument("--renderability", choices=("strict", "repair"), default="repair")
    bundle_compile.add_argument(
        "--spacy", choices=("auto", "off", "sm", "md", "lg", "trf"), default="auto"
    )
    bundle_compile.add_argument("--force", action="store_true")
    bundle_compile.add_argument("--fail-fast", action="store_true")
    bundle_compile.add_argument("--report", type=Path)
    bundle_compile.add_argument(
        "--diagnostics", choices=("warnings", "all", "none"), default="warnings"
    )

    bundle_render = bundle_commands.add_parser("render", help="render a book or document bundle")
    bundle_render.add_argument(
        "workspace", type=Path, help="path resolving to a canonical NAME.ssmd-bundle directory"
    )
    bundle_render.add_argument("--profile", type=Path, required=True)
    bundle_render.add_argument("--chapters", default="all", metavar="SELECTOR")
    bundle_render.add_argument(
        "--pause-timing",
        choices=("fixed", "natural", "engaging"),
        default=None,
        help="automatic semantic pause timing for the projected RenderPlans",
    )
    bundle_render.add_argument("--variant")
    bundle_render.add_argument("--utterplan-dir", type=Path)
    bundle_render.add_argument("--output-root", type=Path)
    bundle_render.add_argument("--report", type=Path)
    bundle_render.add_argument(
        "--force",
        action="store_true",
        help=(
            "replace valid existing RenderPlan outputs; does not bypass RenderProfile validation"
        ),
    )
    bundle_render.add_argument("--fail-fast", action="store_true")

    bundle_replan = bundle_commands.add_parser("replan", help="refine active bundle RenderPlans")
    bundle_replan.add_argument(
        "workspace", type=Path, help="path resolving to a canonical NAME.ssmd-bundle directory"
    )
    bundle_replan.add_argument("--variant", required=True, help="exact existing RenderPlan variant")
    bundle_replan.add_argument("--chapters", default="all", metavar="SELECTOR")
    bundle_replan.add_argument("--renderplan-root", type=Path)
    bundle_replan.add_argument("--voicerender-root", type=Path)
    bundle_replan.add_argument("--report", type=Path)
    bundle_replan.add_argument("--dry-run", action="store_true")
    bundle_replan.add_argument("--fail-fast", action="store_true")
    bundle_replan.add_argument("--explain", action="store_true")
    bundle_replan.add_argument("--json", action="store_true")

    validate_parser = commands.add_parser(
        "validate", help="validate a source document or saved semantic plan"
    )
    validate_parser.add_argument("input", type=Path)

    validate_parser.add_argument("--language", "--lang", dest="language")
    validate_parser.add_argument(
        "--input-format",
        choices=("auto", "text", "plain", "ssmd"),
        default="auto",
        help="source input interpretation; auto detects SSMD by suffix or version metadata",
    )

    migrate_parser = commands.add_parser(
        "migrate",
        help="migrate supported legacy JSON or v4/v5/v6 TOML plans to the current v7 TOML format",
    )
    migrate_parser.add_argument("input", type=Path)
    migrate_parser.add_argument("-o", "--output", type=Path)
    migrate_parser.add_argument(
        "--force", action="store_true", help="replace an existing output file"
    )
    migrate_parser.add_argument(
        "--check", action="store_true", help="check migration feasibility without writing"
    )

    explain_parser = commands.add_parser(
        "explain", help="explain a saved TTS plan in human-readable form"
    )
    explain_parser.add_argument("input", type=Path)
    explain_parser.add_argument(
        "--details",
        action="store_true",
        help="include IDs, offsets, provenance, and plan identity details",
    )
    explain_parser.add_argument("--trace", type=Path, help="optional compiler trace sidecar")
    preview_parser = commands.add_parser(
        "preview", help="project a saved plan into renderer-neutral downstream chunks"
    )
    preview_parser.add_argument("input", type=Path, help="saved schema-v7 .utterplan.toml plan")
    preview_parser.add_argument(
        "--segments",
        metavar="SELECTOR",
        help="global zero-based segment indexes: N, N-M, comma lists, or all",
    )
    preview_parser.add_argument(
        "--chunk-by",
        choices=("segment", "clause", "sentence", "paragraph"),
        default="sentence",
        help="downstream chunk grouping (default: sentence)",
    )
    preview_parser.add_argument(
        "--pause-policy",
        choices=("native", "automatic", "manual"),
        default="native",
        help="pause projection policy (default: native)",
    )
    preview_parser.add_argument(
        "--details", action="store_true", help="show stored constituent segments and local facts"
    )
    preview_parser.add_argument(
        "--json", action="store_true", help="emit stable machine-readable preview data"
    )
    render_plan_parser = commands.add_parser(
        "render-plan",
        help="project a schema-v7 UtterPlan into a portable RenderPlan",
    )
    render_plan_parser.add_argument(
        "input", type=Path, help="current schema-v7 .utterplan.toml file"
    )
    render_plan_parser.add_argument(
        "--profile", type=Path, required=True, help="RenderProfile TOML file"
    )
    render_plan_parser.add_argument(
        "--previous", type=Path, help="prior RenderPlan TOML for deterministic replanning"
    )
    render_plan_parser.add_argument(
        "--preflight", type=Path, help="matching RenderPlan preflight report TOML"
    )
    render_plan_parser.add_argument(
        "--pause-timing",
        choices=("fixed", "natural", "engaging"),
        default=None,
        help=(
            "automatic semantic pause timing: fixed preserves RenderProfile durations, "
            "natural adds moderate context adaptation, engaging uses stronger dynamics"
        ),
    )
    render_plan_parser.add_argument(
        "-o", "--output", type=Path, required=True, help="write the RenderPlan TOML"
    )
    render_plan_parser.add_argument(
        "--force",
        action="store_true",
        help="replace valid existing output; does not bypass profile validation",
    )
    render_plan_parser.add_argument(
        "--explain", action="store_true", help="print in-memory planning decisions"
    )
    render_plan_parser.add_argument(
        "--json", action="store_true", help="emit the generated plan as machine-readable JSON"
    )
    inspect_parser = commands.add_parser("inspect", help="inspect a saved TTS plan")
    inspect_parser.add_argument("input", type=Path)
    inspect_parser.add_argument("--unit", type=int)
    inspect_parser.add_argument("--segment", type=int)
    inspect_parser.add_argument("--warnings", action="store_true")
    inspect_parser.add_argument("--boundaries", action="store_true")
    inspect_parser.add_argument("--tokens", action="store_true")
    inspect_parser.add_argument(
        "--roles",
        action="store_true",
        help="show logical voice roles referenced by speech segments",
    )
    inspect_parser.add_argument(
        "--semantic-boundaries",
        action="store_true",
        help="show semantic split opportunities in spoken coordinates",
    )
    inspect_parser.add_argument("--preparation", action="store_true")

    trace_inspect_parser = commands.add_parser(
        "inspect-trace", help="inspect compiler provenance from an optional trace sidecar"
    )
    trace_inspect_parser.add_argument("input", type=Path)
    trace_inspect_parser.add_argument("--boundaries", action="store_true")
    trace_inspect_parser.add_argument("--preparation", action="store_true")
    trace_inspect_parser.add_argument(
        "--json", action="store_true", help="emit the full trace as JSON"
    )

    attempt_inspect_parser = commands.add_parser(
        "inspect-attempt", help="inspect a persisted planning-attempt artifact"
    )
    attempt_inspect_parser.add_argument("input", type=Path)
    attempt_inspect_parser.add_argument("--issues", action="store_true")
    attempt_inspect_parser.add_argument("--segment", help="inspect one segment by ID or index")
    attempt_inspect_parser.add_argument("--unit", help="inspect one unit by ID or index")
    attempt_inspect_parser.add_argument(
        "--json", action="store_true", help="emit the full attempt as JSON"
    )
    return parser


def _ssmd_header_language(source: str) -> str | None:
    try:
        from ssmd.frontmatter import FrontMatterError, parse_front_matter
    except ImportError:
        return None
    try:
        front_matter = parse_front_matter(source)
    except FrontMatterError as exc:
        raise PlanFormatError(str(exc), code=exc.code, path="$.source") from exc
    language = front_matter.data.get("language") if front_matter.present else None
    return language.strip() if isinstance(language, str) and language.strip() else None


def _format_for_path(path: Path, source: str) -> InputFormat:
    """Keep the legacy CLI auto-detection helper as a compatibility shim."""
    return _format_source_path(path, source, "auto")


def _language_fallback(source: str, input_format: InputFormat, requested: str | None) -> str:
    if requested is not None:
        if not requested.strip():
            raise ValueError("--language must be a non-empty fallback language")
        return requested.strip()
    if input_format == "ssmd":
        language = _ssmd_header_language(source)
        if language is not None:
            return language
        raise ValueError("SSMD input without a header language requires --language")
    raise ValueError("plain input requires --language")


def _read_compile_input(args: argparse.Namespace) -> tuple[str, InputFormat]:
    requested_format = (
        "auto" if args.input_format == "auto" else _map_input_format(args.input_format)
    )
    if args.file is not None:
        if args.text:
            raise ValueError("--file cannot be combined with positional text")
        loaded = load_source_path(args.file, requested_format=requested_format)
        return loaded.text, loaded.input_format

    if not args.text:
        if sys.stdin.isatty():
            raise ValueError("no input text supplied; provide text or pipe data on stdin")
        source = sys.stdin.read()
        if not source.strip():
            raise ValueError("stdin is empty; provide meaningful input text")
        return source, _map_input_format(args.input_format, default="plain")

    if args.input_format in {"text", "plain"}:
        return " ".join(args.text), "plain"

    if len(args.text) == 1:
        candidate = Path(args.text[0])
        if candidate.exists() or candidate.is_symlink():
            loaded = load_source_path(candidate, requested_format=requested_format)
            return loaded.text, loaded.input_format

    return " ".join(args.text), _map_input_format(args.input_format, default="plain")


def _map_input_format(value: str, *, default: InputFormat = "plain") -> InputFormat:
    if value in {"text", "plain"}:
        return "plain"
    if value == "ssmd":
        return "ssmd"
    return default


def _linguistics_config(policy: str) -> LinguisticsConfig:
    if policy == "off":
        return LinguisticsConfig(use_spacy=False)
    if policy == "auto":
        return LinguisticsConfig(use_spacy=True)
    return LinguisticsConfig(
        use_spacy=True,
        spacy_model_size=cast(Literal["sm", "md", "lg", "trf"], policy),
        require_spacy=True,
    )


def _planner_config_from_batch_args(args: argparse.Namespace) -> PlannerConfig:
    return PlannerConfig(
        language=args.language or "en-US",
        document_format="plain",
        text_preparation=args.text_preparation,
        linguistics=_linguistics_config(args.spacy),
        renderability_mode=args.renderability,
    )


def _run_compile_requests(
    requests: list[CompileRequest],
    *,
    config: PlannerConfig,
    fail_fast: bool,
    force: bool,
    report_path: Path,
    include_ids: bool = False,
    diagnostics: Literal["warnings", "all", "none"] = "warnings",
) -> int:
    outcomes: list[CompileOutcome] = []
    iterator = iter(
        compile_to_files(
            requests,
            config=config,
            fail_fast=fail_fast,
            force=force,
            report_path=report_path,
        )
    )
    total = len(requests)
    written = 0
    for index, request in enumerate(requests, start=1):
        source_label = request.source_label or str(request.source)
        progress_label = f"{request.id}  {source_label}" if include_ids else source_label
        print(f"[{index}/{total}] {progress_label}", file=sys.stderr)
        outcome = next(iterator)
        outcomes.append(outcome)
        if outcome.status == "written":
            written += 1
            if include_ids:
                mode = outcome.preparation_mode or "unknown"
                linguistics = "degraded" if outcome.degraded_linguistics else "full"
                print(
                    f"       preparation: {mode}; linguistics: {linguistics}",
                    file=sys.stderr,
                )
            _print_batch_diagnostics(outcome, verbosity=diagnostics)
            print(f"       wrote {outcome.output}", file=sys.stderr)
        elif outcome.status == "failed":
            print("       FAILED", file=sys.stderr)
            if outcome.error_message:
                for line in outcome.error_message.splitlines():
                    print(f"       {line}", file=sys.stderr)
            if not fail_fast and index < total:
                next_request = requests[index]
                next_label = next_request.source_label or next_request.id
                print(
                    f"       continuing with {next_label}; {written} plans are already saved",
                    file=sys.stderr,
                )
        else:
            print("       skipped after an earlier failure", file=sys.stderr)

    with suppress(StopIteration):
        next(iterator)

    failed = [outcome for outcome in outcomes if outcome.status == "failed"]
    skipped = sum(outcome.status == "skipped" for outcome in outcomes)
    print("UtterPlan compile summary", file=sys.stderr)
    print(f"  requested: {total}", file=sys.stderr)
    print(f"  written:   {written}", file=sys.stderr)
    print(f"  failed:    {len(failed)}", file=sys.stderr)
    if skipped:
        print(f"  skipped:   {skipped}", file=sys.stderr)
    if failed:
        print("\nFailed:", file=sys.stderr)
        for outcome in failed:
            location = (
                f":{outcome.line}:{outcome.column}"
                if outcome.line is not None and outcome.column is not None
                else ""
            )
            code = outcome.error_code or "unknown"
            print(
                f"  [{outcome.index}/{total}] {outcome.source_label}{location}  {code}",
                file=sys.stderr,
            )
        if written:
            print(f"\n{written} valid plan files were preserved.", file=sys.stderr)
    return 1 if failed else 0


def _print_batch_diagnostics(
    outcome: CompileOutcome,
    *,
    verbosity: Literal["warnings", "all", "none"],
) -> None:
    labels: tuple[tuple[str, str], ...]
    if verbosity == "all":
        selected = outcome.diagnostics
        labels = (("info", "info"), ("warning", "warnings"), ("error", "errors"))
    elif verbosity == "warnings":
        selected = tuple(
            diagnostic
            for diagnostic in outcome.diagnostics
            if diagnostic.severity in {"warning", "error"}
        )
        labels = (("warning", "warnings"), ("error", "errors"))
    else:
        selected = tuple(
            diagnostic for diagnostic in outcome.diagnostics if diagnostic.severity == "error"
        )
        labels = (("error", "errors"),)

    for severity, label in labels:
        count = sum(diagnostic.severity == severity for diagnostic in selected)
        if count:
            print(f"       {label}: {count}", file=sys.stderr)
    for diagnostic in selected:
        location = (
            f"source[{diagnostic.source_start}:{diagnostic.source_end}]"
            if diagnostic.source_start is not None and diagnostic.source_end is not None
            else f"{diagnostic.line}:{diagnostic.column}"
            if diagnostic.line is not None and diagnostic.column is not None
            else "source"
        )
        print(
            f"       {diagnostic.code} at {location}: {diagnostic.message}",
            file=sys.stderr,
        )


def _compile_many(args: argparse.Namespace) -> int:
    sources: list[Path] = args.inputs
    outputs = [args.output_dir / _utterplan_output_name(source) for source in sources]
    owners: dict[Path, Path] = {}
    for source, output in zip(sources, outputs, strict=True):
        key = output.resolve()
        if key in owners:
            raise _CliUsageError(
                f"inputs {owners[key]} and {source} map to the same output {output}"
            )
        owners[key] = source

    report_path = args.report or (args.output_dir / "compile-report.toml")
    if report_path.resolve() in owners:
        raise _CliUsageError(f"batch report path collides with plan output: {report_path}")

    requests = [
        CompileRequest(
            id=f"item-{index:06d}",
            source=source,
            output=output,
            input_format=cast(Literal["auto", "plain", "ssmd"], args.input_format),
            fallback_language=args.language,
            source_label=str(source),
            require_language=args.language is None,
        )
        for index, (source, output) in enumerate(zip(sources, outputs, strict=True), start=1)
    ]
    return _run_compile_requests(
        requests,
        config=_planner_config_from_batch_args(args),
        fail_fast=args.fail_fast,
        force=args.force,
        report_path=report_path,
        diagnostics=args.diagnostics,
    )


def _compile_bundle(args: argparse.Namespace) -> int:
    selected_ids: tuple[str, ...] = ()
    written = 0

    def start(progress: BundleCompileStart) -> None:
        nonlocal selected_ids
        selected_ids = progress.selected_item_ids
        print("UtterPlan bundle compile", file=sys.stderr)
        print(f"  kind:      {progress.kind}", file=sys.stderr)
        print(f"  workspace: {progress.workspace}", file=sys.stderr)
        if progress.kind == "book":
            print(f"  chapters:  {progress.selector}", file=sys.stderr)
        print(f"  selected:  {len(selected_ids)}", file=sys.stderr)
        print(f"  output:    {progress.output_dir}", file=sys.stderr)
        print(f"  report:    {progress.report_path}", file=sys.stderr)

    def report_progress(outcome: CompileOutcome) -> None:
        nonlocal written
        total = outcome.total or len(selected_ids)
        print(
            f"[{outcome.index}/{total}] {outcome.id}  {outcome.source_label}",
            file=sys.stderr,
        )
        if outcome.status == "written":
            written += 1
            mode = outcome.preparation_mode or "unknown"
            linguistics = "degraded" if outcome.degraded_linguistics else "full"
            print(f"       preparation: {mode}; linguistics: {linguistics}", file=sys.stderr)
            _print_batch_diagnostics(outcome, verbosity=args.diagnostics)
            print(f"       wrote {outcome.output}", file=sys.stderr)
        elif outcome.status == "failed":
            print("       FAILED", file=sys.stderr)
            if outcome.error_message:
                for line in outcome.error_message.splitlines():
                    print(f"       {line}", file=sys.stderr)
        else:
            print("       skipped after an earlier failure", file=sys.stderr)

    try:
        result = _compile_bundle_service(
            args.workspace,
            chapters=args.chapters,
            output_dir=args.output_dir,
            report=args.report,
            language=args.language,
            planner_config=_planner_config_from_batch_args(args),
            force=args.force,
            fail_fast=args.fail_fast,
            diagnostics=args.diagnostics,
            on_progress=report_progress,
            on_start=start,
        )
    except BundleServiceError as exc:
        raise _CliUsageError(str(exc)) from exc

    print("UtterPlan bundle compile summary", file=sys.stderr)
    print(f"  kind:      {result.kind}", file=sys.stderr)
    print(f"  requested: {len(result.outcomes)}", file=sys.stderr)
    print(f"  written:   {written}", file=sys.stderr)
    print(f"  failed:    {result.failed}", file=sys.stderr)
    print(f"  report:    {result.report_path}", file=sys.stderr)
    if result.role_inventory_path is not None:
        inventory = load_bundle_role_inventory(result.role_inventory_path)
        role_names = ", ".join(role.name for role in inventory.roles) or "(none)"
        default_role = (
            f"required by {inventory.implicit_occurrences} speech segments"
            if inventory.uses_default_role
            else "not used"
        )
        print(f"  roles:           {role_names}", file=sys.stderr)
        print(f"  default-role:    {default_role}", file=sys.stderr)
        print(f"  role inventory:  {result.role_inventory_path}", file=sys.stderr)
    return result.exit_code


def _render_bundle(args: argparse.Namespace) -> int:
    selected_ids: tuple[str, ...] = ()
    written = 0

    def start(progress: BundleRenderStart) -> None:
        nonlocal selected_ids
        selected_ids = progress.selected_item_ids
        print("UtterPlan bundle render", file=sys.stderr)
        print(f"  kind:      {progress.kind}", file=sys.stderr)
        print(f"  workspace: {progress.workspace}", file=sys.stderr)
        if progress.kind == "book":
            print(f"  chapters:  {progress.selector}", file=sys.stderr)
        print(f"  selected:  {len(selected_ids)}", file=sys.stderr)
        print(f"  profile:   {args.profile}", file=sys.stderr)
        print(f"  variant:   {progress.variant}", file=sys.stderr)
        print(f"  pause timing: {args.pause_timing or 'fixed'}", file=sys.stderr)
        if progress.required_roles:
            print(f"  roles:      {', '.join(progress.required_roles)}", file=sys.stderr)
        print("  coverage:   complete", file=sys.stderr)
        for path in progress.output_paths:
            print(f"  output:    {path}", file=sys.stderr)
        print(f"  report:    {progress.report_path}", file=sys.stderr)

    def report_progress(outcome: RenderOutcome) -> None:
        nonlocal written
        total = outcome.total or len(selected_ids)
        print(f"[{outcome.index}/{total}] {outcome.id}  {outcome.source_plan}", file=sys.stderr)
        if outcome.status == "written":
            written += 1
            print(f"       wrote {outcome.output}", file=sys.stderr)
        elif outcome.status == "failed":
            print(
                f"       FAILED {outcome.error_code or 'unknown'}: "
                f"{outcome.error_message or 'projection failed'}",
                file=sys.stderr,
            )
        else:
            print("       skipped after an earlier failure", file=sys.stderr)

    try:
        result = _render_bundle_service(
            args.workspace,
            profile=args.profile,
            chapters=args.chapters,
            variant=args.variant,
            pause_timing=(
                PauseTimingConfig(cast(PauseTimingMode, args.pause_timing))
                if args.pause_timing is not None
                else None
            ),
            utterplan_dir=args.utterplan_dir,
            output_root=args.output_root,
            report=args.report,
            force=args.force,
            fail_fast=args.fail_fast,
            on_progress=report_progress,
            on_start=start,
        )
    except BundleServiceError as exc:
        raise _CliUsageError(str(exc)) from exc

    print("UtterPlan bundle render summary", file=sys.stderr)
    print(f"  kind:      {result.kind}", file=sys.stderr)
    print(f"  requested: {len(result.outcomes)}", file=sys.stderr)
    print(f"  written:   {written}", file=sys.stderr)
    print(f"  failed:    {result.failed}", file=sys.stderr)
    print(f"  report:    {result.report_path}", file=sys.stderr)
    return result.exit_code


def _replan_bundle(args: argparse.Namespace) -> int:
    start_info: BundleReplanStart | None = None
    selected_count = 0
    explanations: dict[int, str] = {}

    def start(progress: BundleReplanStart) -> None:
        nonlocal start_info, selected_count
        start_info = progress
        selected_count = len(progress.selected_item_ids)
        if args.json:
            return
        print("UtterPlan bundle replan", file=sys.stderr)
        print(f"  kind:       {progress.kind}", file=sys.stderr)
        print(f"  workspace:  {progress.workspace}", file=sys.stderr)
        print(f"  variant:    {progress.variant}", file=sys.stderr)
        if progress.kind == "book":
            print(f"  chapters:   {progress.selector}", file=sys.stderr)
        print(f"  selected:   {selected_count}", file=sys.stderr)
        print(f"  active:     {progress.active_reference}", file=sys.stderr)
        print(f"  preflights: {progress.voicerender_dir}", file=sys.stderr)

    def report_progress(outcome: ReplanOutcome) -> None:
        if args.json:
            if args.explain and outcome.status in {"written", "planned"} and start_info is not None:
                explanations[outcome.index] = _replan_explanation(outcome, start_info.profile_path)
            return
        print(f"[{outcome.index}/{selected_count}] {outcome.id}", file=sys.stderr)
        if outcome.previous_render_plan_id is not None:
            print(f"       previous: {outcome.previous_render_plan_id}", file=sys.stderr)
        if outcome.preflight is not None:
            print(f"       preflight: {outcome.preflight.name}", file=sys.stderr)
        if outcome.replacement_count:
            print(f"       replacements: {outcome.replacement_count}", file=sys.stderr)
        if outcome.status == "written":
            print(f"       written: {outcome.renderplan}", file=sys.stderr)
            print(f"       active: {outcome.render_plan_id}", file=sys.stderr)
        elif outcome.status == "planned":
            print(f"       planned: {outcome.renderplan}", file=sys.stderr)
            print(f"       would be active: {outcome.render_plan_id}", file=sys.stderr)
        elif outcome.status == "failed":
            print(
                f"       FAILED {outcome.error_code or 'unknown'}: "
                f"{outcome.error_message or 'replan failed'}",
                file=sys.stderr,
            )
        else:
            print("       skipped after an earlier failure", file=sys.stderr)
        if args.explain and start_info is not None and outcome.status in {"written", "planned"}:
            explanation = _replan_explanation(outcome, start_info.profile_path)
            explanations[outcome.index] = explanation
            print(f"       explanation:\n{explanation}", end="", file=sys.stderr)

    try:
        result = _replan_bundle_service(
            args.workspace,
            variant=args.variant,
            chapters=args.chapters,
            renderplan_root=args.renderplan_root,
            voicerender_root=args.voicerender_root,
            report=args.report,
            dry_run=args.dry_run,
            fail_fast=args.fail_fast,
            on_progress=report_progress,
            on_start=start,
        )
    except BundleReplanError as exc:
        raise _CliUsageError(str(exc)) from exc

    if args.json:
        outcomes: list[dict[str, object]] = []
        for outcome in result.outcomes:
            item: dict[str, object] = {
                "index": outcome.index,
                "id": outcome.id,
                "source_number": outcome.source_number,
                "status": outcome.status,
                "utterplan": str(outcome.utterplan) if outcome.utterplan is not None else None,
                "previous_renderplan": (
                    str(outcome.previous_renderplan)
                    if outcome.previous_renderplan is not None
                    else None
                ),
                "previous_render_plan_id": outcome.previous_render_plan_id,
                "preflight": str(outcome.preflight) if outcome.preflight is not None else None,
                "renderplan": str(outcome.renderplan) if outcome.renderplan is not None else None,
                "render_plan_id": outcome.render_plan_id,
                "replacement_count": outcome.replacement_count,
                "stage": outcome.stage,
                "error_code": outcome.error_code,
                "error_message": outcome.error_message,
            }
            if args.explain and outcome.index in explanations:
                item["explanation"] = explanations[outcome.index]
            outcomes.append(item)
        print(
            json.dumps(
                {
                    "format": "utterplan-replan-bundle",
                    "version": 1,
                    "kind": result.kind,
                    "workspace": str(result.workspace),
                    "variant": result.variant,
                    "active_reference": str(result.active_reference),
                    "report_path": str(result.report_path),
                    "selected_item_ids": list(result.selected_item_ids),
                    "dry_run": result.dry_run,
                    "written": result.written,
                    "planned": result.planned,
                    "failed": result.failed,
                    "skipped": result.skipped,
                    "outcomes": outcomes,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return result.exit_code

    print("UtterPlan bundle replan summary", file=sys.stderr)
    print(f"  kind:      {result.kind}", file=sys.stderr)
    print(f"  requested: {len(result.outcomes)}", file=sys.stderr)
    print(f"  written:   {result.written}", file=sys.stderr)
    if result.dry_run:
        print(f"  planned:   {result.planned} (dry run; no plans written)", file=sys.stderr)
    print(f"  failed:    {result.failed}", file=sys.stderr)
    if result.skipped:
        print(f"  skipped:   {result.skipped}", file=sys.stderr)
    print(f"  active:    {result.active_reference}", file=sys.stderr)
    print(f"  report:    {result.report_path}", file=sys.stderr)
    return result.exit_code


def _replan_explanation(outcome: ReplanOutcome, profile_path: Path) -> str:
    if (
        outcome.utterplan is None
        or outcome.previous_renderplan is None
        or outcome.preflight is None
    ):
        return ""
    source_plan = FlowPlan.load(outcome.utterplan)
    profile = load_render_profile(profile_path).profile
    previous = renderplan_codec.load_plan(outcome.previous_renderplan)
    preflight = renderplan_codec.load_preflight(outcome.preflight)
    plan = build_render_plan(
        source_plan,
        profile,
        previous_plan=previous,
        preflight=preflight,
    ).with_identity()
    return format_render_plan_explanation(plan, previous_plan=previous, preflight=preflight)


def _compile(args: argparse.Namespace) -> int:
    source, input_format = _read_compile_input(args)
    trace_path: Path | None = args.trace
    paths = [path for path in (args.output, trace_path) if path is not None]
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("plan output and trace output must use different paths")
    if not args.force:
        existing = next((path for path in paths if path.exists()), None)
        if existing is not None:
            raise ValueError(f"output exists: {existing}; use --force to replace it")

    fallback_language = _language_fallback(source, input_format, args.language)
    config = PlannerConfig(
        language=fallback_language,
        document_format=input_format,
        text_preparation=args.text_preparation,
        linguistics=_linguistics_config(args.spacy),
        renderability_mode=args.renderability,
    )
    result = compile_document(
        source,
        input_format=input_format,
        config=config,
        fallback_language=args.language,
        trace=trace_path is not None,
    )
    plan = result.plan
    payload = plan.to_toml()
    if trace_path is not None:
        if result.trace is None:
            raise RuntimeError("trace was requested but the compiler returned no trace")
        atomic_write_text(trace_path, result.trace.to_toml(), create_parent=True)

    segment_count = sum(len(unit.segments) for unit in plan.flow)
    if args.output is None:
        print(payload, end="")
    else:
        atomic_write_text(args.output, payload, create_parent=True)
        if args.stdout:
            print(payload, end="")
        else:
            print(
                f"wrote {args.output} ({segment_count} segments, {len(plan.flow)} units)",
                file=sys.stderr,
            )
    if args.renderability == "repair":
        repair_count = sum(
            diagnostic.code == "planning.renderability.repaired"
            for diagnostic in result.diagnostics
        )
        if repair_count:
            suffix = "s" if repair_count != 1 else ""
            print(
                f"renderability: guaranteed; {repair_count} punctuation segment{suffix} repaired",
                file=sys.stderr,
            )
    return 0


def _format_renderability_error(error: PlanRenderabilityError, args: argparse.Namespace) -> str:
    source_label = str(args.file) if getattr(args, "file", None) is not None else "input"
    positional = getattr(args, "text", None)
    if source_label == "input" and isinstance(positional, list) and len(positional) == 1:
        candidate = Path(positional[0])
        if candidate.is_file():
            source_label = str(candidate)
    return format_renderability_error(error, source_label=source_label)


def _migration_result(path: Path) -> MigrationResult:
    content = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".toml":
        try:
            wire = tomlkit.parse(content).unwrap()
        except ParseError as exc:
            line = getattr(exc, "line", None)
            column = getattr(exc, "col", None)
            location = f"line {line}, column {column}: " if line is not None else ""
            raise PlanFormatError(f"{location}{exc}", code="toml.invalid") from exc
        if not isinstance(wire, dict):
            raise PlanFormatError("TOML root must be a table", code="toml.root")
        version = wire.get("schema_version")
        if version == 4:
            from .codecs.v4_toml import decode_v4_toml_data

            return migrate_plan_data(decode_v4_toml_data(wire))
        if version in {V5_SCHEMA_VERSION, V6_SCHEMA_VERSION, CURRENT_SCHEMA_VERSION}:
            if version == V5_SCHEMA_VERSION:
                from .codecs.v5_toml import from_v5_toml_data

                legacy = from_v5_toml_data(wire)
                return migrate_plan_data(legacy.to_dict())
            if version == V6_SCHEMA_VERSION:
                from .codecs.v6_toml import from_v6_toml_data

                legacy = from_v6_toml_data(wire)
                return migrate_plan_data(legacy.to_dict())
            plan = FlowPlan.from_toml(content)
            return migrate_plan_data(plan.to_dict())
        raise PlanFormatError(
            "migrate supports schema-v4/v5/v6/v7 TOML plan files", code="schema.version"
        )
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise PlanFormatError(str(exc), code="json.invalid") from exc
    return migrate_plan_data(value)


def _migration_steps(result: MigrationResult) -> str:
    return " -> ".join(
        [str(result.source_version), *(str(step.target_version) for step in result.steps)]
    )


def _migrate(args: argparse.Namespace) -> int:
    result = _migration_result(args.input)
    steps = _migration_steps(result)
    if args.check:
        print("valid migration path")
        print(f"source schema: {result.source_version}")
        print(f"target schema: {result.target_version}")
        print(f"migration required: {'yes' if result.changed else 'no'}")
        if result.steps:
            print(f"steps: {steps}")
        return 0

    plan = FlowPlan.from_dict(result.data)
    payload = plan.to_toml()
    if args.output is None:
        print(payload, end="")
    else:
        if args.output.exists() and not args.force:
            raise ValueError(f"output exists: {args.output}; use --force to replace it")
        atomic_write_text(args.output, payload, create_parent=True)
        print(
            f"imported {args.input} as TOML (schema {result.source_version} -> {result.target_version})",
            file=sys.stderr,
        )
    return 0


def _validate(args: argparse.Namespace) -> int:
    path: Path = args.input
    name = path.name.lower()
    if name.endswith(".utterplan.json") or path.suffix.lower() == ".json":
        raise PlanFormatError(
            "JSON is not a supported plan-file format; use 'utterplan migrate INPUT.json -o OUTPUT.utterplan.toml'",
            code="format.unsupported_json",
        )
    if name.endswith(".utterplan.toml") or path.suffix.lower() == ".toml":
        plan = FlowPlan.from_toml(path.read_text(encoding="utf-8"))
        print("valid")
        print(f"schema version: {plan.schema_version}")
        print(f"plan ID: {plan.plan_id}")
        print(f"segments: {_flow_segment_count(plan)}")
        print(f"units: {len(plan.flow)}")
        print(f"warnings: {len(plan.warnings)}")
        return 0

    loaded = load_source_path(
        path,
        requested_format=(
            "auto" if args.input_format == "auto" else _map_input_format(args.input_format)
        ),
    )
    source = loaded.text
    input_format = loaded.input_format
    fallback_language = _language_fallback(source, input_format, args.language)
    config = PlannerConfig(
        language=fallback_language,
        document_format=input_format,
        text_preparation="identity",
        linguistics=LinguisticsConfig(use_spacy=False),
    )
    compile_result = compile_document(
        source,
        input_format=input_format,
        config=config,
        fallback_language=args.language,
    )
    print("valid")
    print(f"input format: {input_format}")
    print(f"segments: {_flow_segment_count(compile_result.plan)}")
    print(f"units: {len(compile_result.plan.flow)}")
    print(f"warnings: {len(compile_result.plan.warnings)}")
    return 0


def _flow_segment_count(plan: FlowPlan) -> int:
    return sum(len(unit.segments) for unit in plan.flow)


def _load_plan_file(path: Path) -> FlowPlan:
    name = path.name.lower()
    if name.endswith(".utterplan.json") or path.suffix.lower() == ".json":
        raise PlanFormatError(
            "JSON is not a supported plan-file format; use 'utterplan migrate INPUT.json -o OUTPUT.utterplan.toml'",
            code="format.unsupported_json",
        )
    return FlowPlan.from_toml(path.read_text(encoding="utf-8"))


def _render_plan_command(args: argparse.Namespace) -> int:
    if (args.previous is None) != (args.preflight is None):
        raise _CliUsageError("--previous and --preflight must be supplied together")
    if args.previous is not None and args.pause_timing is not None:
        raise _CliUsageError(
            "--pause-timing applies only to initial RenderPlan projection; "
            "replanning preserves pause timing from --previous"
        )
    if args.output.exists() and not args.force:
        raise _CliUsageError(f"output exists: {args.output}; use --force to replace it")

    source = _load_plan_file(args.input)
    profile = load_render_profile(args.profile).profile
    coverage = profile_role_coverage(source, profile)
    previous = renderplan_codec.load_plan(args.previous) if args.previous is not None else None
    preflight = (
        renderplan_codec.load_preflight(args.preflight) if args.preflight is not None else None
    )
    plan = build_render_plan(
        source,
        profile,
        previous_plan=previous,
        preflight=preflight,
        pause_timing=(
            PauseTimingConfig(cast(PauseTimingMode, args.pause_timing))
            if args.pause_timing is not None
            else None
        ),
    )
    timing_mode = args.pause_timing or ("preserved" if previous is not None else "fixed")
    timing_provenance: dict[str, object] = {
        "mode": timing_mode,
        "algorithm": PAUSE_TIMING_ALGORITHM if previous is None else None,
    }
    renderplan_codec.save_plan(plan, args.output)

    explanation = (
        format_render_plan_explanation(plan, previous_plan=previous, preflight=preflight)
        if args.explain
        else None
    )
    if args.json:
        payload: dict[str, object] = {
            "format": "utterplan-render-plan",
            "version": 1,
            "output": str(args.output),
            "pause_timing": timing_provenance,
            "role_coverage": {
                "default_role": coverage.default_role,
                "required": list(coverage.required_roles),
                "available": list(coverage.available_roles),
                "missing": list(coverage.missing_roles),
                "uses_default_role": coverage.uses_default_role,
            },
            "plan": renderplan_codec.plan_to_dict(plan),
        }
        if explanation is not None:
            payload["explanation"] = explanation
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"roles: {', '.join(coverage.required_roles) or 'none'}", file=sys.stderr)
        print("coverage: complete", file=sys.stderr)
        print(f"pause timing: {timing_mode}", file=sys.stderr)
        if explanation is not None:
            print(explanation, end="")
        else:
            print(f"wrote {args.output}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "compile":
            return _compile(args)
        if args.command == "compile-many":
            return _compile_many(args)
        if args.command == "bundle":
            if args.bundle_command == "compile":
                return _compile_bundle(args)
            if args.bundle_command == "render":
                return _render_bundle(args)
            if args.bundle_command == "replan":
                return _replan_bundle(args)
        if args.command == "migrate":
            return _migrate(args)
        if args.command == "validate":
            return _validate(args)
        if args.command == "inspect-attempt":
            _inspect_attempt(PlanningAttempt.load(args.input), args)
            return 0
        if args.command == "inspect-trace":
            _inspect_trace(loads_trace(args.input.read_text(encoding="utf-8")), args)
            return 0
        if args.command == "render-plan":
            return _render_plan_command(args)
        plan = _load_plan_file(args.input)
        if args.command == "preview":
            _preview(plan, args)
            return 0
        if args.command == "explain":
            trace = loads_trace(args.trace.read_text(encoding="utf-8")) if args.trace else None
            print(format_explanation(plan, details=args.details, trace=trace), end="")
            return 0
        _inspect(plan, args)
        return 0
    except _CliUsageError as exc:
        print(f"utterplan: {exc}", file=sys.stderr)
        return 2
    except PlanRenderabilityError as exc:
        print(_format_renderability_error(exc, args), file=sys.stderr)
        return 1
    except (OSError, UtterPlanError, ValueError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _preview(plan: FlowPlan, args: argparse.Namespace) -> None:
    chunks = preview_plan(
        plan,
        segments=args.segments,
        chunk_by=args.chunk_by,
        pause_policy=args.pause_policy,
    )
    values: list[dict[str, object]] = []
    for chunk in chunks:
        value = chunk.to_dict()
        if args.details:
            value["constituents"] = _preview_constituents(plan, chunk)
        values.append(value)

    if args.json:
        print(
            json.dumps(
                {
                    "format": "utterplan-preview",
                    "version": 1,
                    "plan_id": plan.plan_id,
                    "chunk_by": args.chunk_by,
                    "pause_policy": args.pause_policy,
                    "chunks": values,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return

    for chunk in chunks:
        suffix = _preview_pause_label(chunk, args.pause_policy)
        line = f"[{chunk.index}] {json.dumps(chunk.text, ensure_ascii=False)}"
        if suffix:
            line += f"  {suffix}"
        print(line)
        if args.details:
            print(f"    boundary.before: {', '.join(chunk.boundary_before) or '-'}")
            print(f"    boundary.after:  {', '.join(chunk.boundary_after) or '-'}")
            constituents = _preview_constituents(plan, chunk)
            for ref, facts in zip(chunk.segments, constituents, strict=True):
                segment = plan.flow[ref.unit_index].segments[ref.local_index]
                print(
                    f"    segment[{ref.global_index}] unit={ref.unit_index} local={ref.local_index}: "
                    f"{json.dumps(segment.text, ensure_ascii=False)}"
                )
                for key in (
                    "language",
                    "pause_before",
                    "pause_after",
                    "directives",
                    "tokens",
                    "replacements",
                    "markers",
                    "heading",
                ):
                    fact_value = facts.get(key)
                    if fact_value not in (None, [], {}):
                        print(
                            f"      {key}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}"
                        )


def _preview_constituents(plan: FlowPlan, chunk: PreviewChunk) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for ref in chunk.segments:
        segment = plan.flow[ref.unit_index].segments[ref.local_index]
        result.append(
            {
                "ref": ref.to_dict(),
                "text": segment.text,
                "language": segment.language,
                "boundary_before": list(segment.boundary_before),
                "boundary_after": list(segment.boundary_after),
                "pause_before": (
                    segment.pause_before.to_dict() if segment.pause_before is not None else None
                ),
                "pause_after": (
                    segment.pause_after.to_dict() if segment.pause_after is not None else None
                ),
                "directives": segment.directives.to_dict(),
                "tokens": [token.to_dict() for token in segment.tokens],
                "replacements": [replacement.to_dict() for replacement in segment.replacements],
                "markers": list(segment.markers),
                "heading": segment.heading,
            }
        )
    return result


def _preview_pause_label(chunk: PreviewChunk, policy: str) -> str:
    labels: list[str] = []
    before = chunk.authored_pause_before
    after = chunk.authored_pause_after
    if before is not None:
        labels.append(f"pause.before.authored={_pause_label(before)}")
    if after is not None:
        labels.append(f"pause.authored={_pause_label(after)}")

    automatic = chunk.automatic_pause
    if automatic is not None:
        boundary = automatic
        if automatic == "clause" and chunk.text.rstrip().endswith(","):
            boundary += " (comma)"
        if policy == "manual":
            if after is not None and after.type != "none":
                labels.append(f"boundary={boundary}")
            else:
                labels.append(f"pause={boundary}")
        elif policy == "automatic":
            labels.append(f"pause={boundary}")
    return " ".join(labels)


def _pause_label(pause: PauseIntent) -> str:
    if pause.type == "timed":
        return pause.time if pause.time is not None else "timed"
    return pause.type


def _inspect(plan: FlowPlan, args: argparse.Namespace) -> None:
    segments = [
        (unit_index, segment_index, segment)
        for unit_index, unit in enumerate(plan.flow)
        for segment_index, segment in enumerate(unit.segments)
    ]
    print(f"Default language: {plan.language}")
    print(f"Schema version: {plan.schema_version}")
    print(f"Plan ID: {plan.plan_id}")
    print(f"Units: {len(plan.flow)}")
    print(f"Segments: {len(segments)}")
    print(f"Linguistic provenance: {len(plan.linguistics)}")
    print(f"Warnings: {len(plan.warnings)}")

    if args.roles:
        inventory = logical_role_inventory(plan)
        print("\nLogical voice roles")
        print("  explicit:")
        if inventory.explicit_occurrences:
            for role, count in inventory.explicit_occurrences.items():
                print(f"    {role}  {count} speech segments")
        else:
            print("    None.")
        print("  default role:")
        if inventory.uses_default_role:
            print(f"    required by {inventory.implicit_occurrences} speech segments")
        else:
            print("    not required")
    if args.warnings:
        if not plan.warnings:
            print("No warnings.")
        for warning in plan.warnings:
            print(f"warning: {warning}")
    if args.preparation or args.semantic_boundaries:
        print("Compiler preparation and boundary candidates are available only in inspect-trace.")
    if args.boundaries:
        print("\nFlow events")
        found = False
        for unit_index, segment_index, segment in segments:
            events: list[str] = []
            if segment.heading is not None:
                events.append(f"heading level {segment.heading}")
            events.extend(f"@{name}" for name in segment.markers)
            for edge, pause in (("before", segment.pause_before), ("after", segment.pause_after)):
                if pause is not None:
                    value = (
                        f"timed {pause.time}"
                        if isinstance(pause, PauseIntent) and pause.type == "timed"
                        else pause.type
                    )
                    events.append(f"pause {edge}: {value}")
            if events:
                found = True
                print(f"  unit {unit_index}, segment {segment_index}: {', '.join(events)}")
        if not found:
            print("  None.")
    if args.tokens:
        print("\nLocal tokens")
        for unit_index, segment_index, segment in segments:
            print(f"  unit {unit_index}, segment {segment_index} [{segment.language}]")
            if not segment.tokens:
                print("    None.")
            for token in segment.tokens:
                surface = segment.text[token.start : token.end]
                print(
                    f"    {token.start}:{token.end} {surface!r}  lemma={token.lemma or '-'}  "
                    f"pos={token.pos or '-'}  tag={token.tag or '-'}  morph={token.morph or '-'}"
                )
    if args.unit is not None:
        if not 0 <= args.unit < len(plan.flow):
            raise _CliUsageError(f"unknown flow unit index {args.unit}")
        unit = plan.flow[args.unit]
        print(f"\nFlow unit {args.unit}")
        for index, segment in enumerate(unit.segments):
            print(f"  segment {index} [{segment.language}]: {segment.text!r}")
    if args.segment is not None:
        if not 0 <= args.segment < len(segments):
            raise _CliUsageError(f"unknown flow segment index {args.segment}")
        unit_index, segment_index, segment = segments[args.segment]
        print(f"\nSegment {args.segment} (unit {unit_index}, local index {segment_index})")
        print(f"  text:         {segment.text!r}")
        print(f"  language:     {segment.language}")
        print(f"  pause_before: {_pause_text(segment.pause_before)}")
        print(f"  pause_after:  {_pause_text(segment.pause_after)}")
        print(f"  heading:      {segment.heading if segment.heading is not None else '-'}")
        print(f"  markers:      {', '.join(segment.markers) or '-'}")
        print(f"  directives:   {segment.directives.to_dict()}")
        for token in segment.tokens:
            print(
                f"  token:        {token.start}:{token.end} {segment.text[token.start : token.end]!r}"
            )


def _pause_text(pause: Any) -> str:
    if pause is None:
        return "-"
    return f"timed {pause.time}" if pause.type == "timed" else pause.type


def _inspect_trace(trace: PreparationTrace, args: argparse.Namespace) -> None:
    if args.json:
        print(json.dumps(trace.to_dict(), ensure_ascii=False, indent=2))
        return
    print("UtterPlan compiler trace")
    print(f"  source hash: {trace.source_sha256}")
    print(f"  source characters: {len(trace.source_text)}")
    print(f"  document language: {trace.document_language}")
    print(f"  sequence fallback: {trace.sequence_fallback_mode}")
    print(f"  diagnostics: {len(trace.diagnostics)}")
    print(f"  warnings: {len(trace.warnings)}")

    compiler_plan = trace.compiler_plan
    if args.preparation:
        preparation = compiler_plan.get("preparation", {})
        preparation = preparation if isinstance(preparation, dict) else {}
        print("\nPreparation")
        print(f"  structural: {len(trace.structural_text)} characters")
        print(f"  spoken: {len(trace.spoken_text)} characters")
        print(f"  backend: {preparation.get('backend', 'unknown')}")
        print(f"  replacements: {len(preparation.get('replacements', []))}")
        print(f"  source spans: {len(trace.source_spans)}")
        print(f"  structural/spoken map points: {len(trace.structural_to_spoken)}")
        for unit in trace.units:
            print(f"  {unit.split_reason}: {unit.source_text!r} -> {unit.prepared_text!r}")
            for change in unit.transformations:
                print(
                    f"    {change.source!r} -> {change.replacement!r} ({change.rule or change.kind})"
                )

    if args.boundaries:
        print("\nBoundary events")
        boundaries = compiler_plan.get("boundaries", [])
        if not isinstance(boundaries, list) or not boundaries:
            print("  None.")
        for boundary in boundaries:
            if not isinstance(boundary, dict):
                continue
            print(
                f"  {boundary.get('id', '-')} {boundary.get('kind', '?')} "
                f"at {boundary.get('position', '?')} ({boundary.get('origin', '?')})"
            )
        semantic = compiler_plan.get("semantic_boundaries", [])
        if isinstance(semantic, list) and semantic:
            print("Semantic boundary candidates")
            for item in semantic:
                if isinstance(item, dict):
                    print(
                        f"  {item.get('id', '-')} {item.get('kind', '?')} "
                        f"at {item.get('position', '?')} ({item.get('origin', '?')})"
                    )


def _inspect_attempt(attempt: PlanningAttempt, args: argparse.Namespace) -> None:
    if args.json:
        print(json.dumps(attempt.to_dict(), ensure_ascii=False, indent=2))
        return

    print("UtterPlan planning attempt")
    print(f"  status:        {attempt.status}")
    print(f"  attempt ID:    {attempt.attempt_id}")
    print(
        f"  renderability: {'guaranteed' if attempt.ok else 'blocked'} ({attempt.renderability_mode})"
    )
    print(
        f"  candidate:    {len(attempt.candidate.segments)} segments, {len(attempt.candidate.units)} units"
    )
    print(f"  issues:       {len(attempt.renderability.issues)}")
    print(f"  repairs:      {len(attempt.repairs)}")

    if args.issues:
        if not attempt.renderability.issues and not attempt.repairs:
            print("\nIssues and repairs: none")
        for issue in attempt.renderability.issues:
            _print_attempt_issue(issue, label="Issue")
        for issue in attempt.repairs:
            _print_attempt_issue(issue, label="Repair")

    if args.segment is not None:
        segment = _attempt_segment(attempt, args.segment)
        print(f"\nSegment {segment.id}: {segment.spoken_start}:{segment.spoken_end}")
        print(f"  text:      {segment.text!r}")
        print(f"  language:  {segment.language}")
        print(f"  structure: {segment.structural_start}:{segment.structural_end}")
        unit_ids = [unit.id for unit in attempt.candidate.units if segment.id in unit.segment_ids]
        print(f"  units:     {', '.join(unit_ids) if unit_ids else '-'}")
        for issue in (*attempt.renderability.issues, *attempt.repairs):
            if issue.segment_id == segment.id:
                _print_attempt_issue(
                    issue, label="Issue" if issue in attempt.renderability.issues else "Repair"
                )

    if args.unit is not None:
        unit = _attempt_unit(attempt, args.unit)
        print(f"\nUnit {unit.id}: {unit.kind} {unit.spoken_start}:{unit.spoken_end}")
        for segment_id in unit.segment_ids:
            segment = next(item for item in attempt.candidate.segments if item.id == segment_id)
            print(f"  {segment.id}: {segment.text!r}")


def _print_attempt_issue(issue: Any, *, label: str) -> None:
    print(f"\n{label} {issue.segment_id}: {issue.code} — {issue.reason}")
    print(f"  text: {issue.text!r}")
    if issue.line is not None:
        location = f"{issue.line}:{issue.column or 1}"
    elif issue.source_start is not None:
        location = f"source {issue.source_start}:{issue.source_end}"
    else:
        location = "source location unavailable"
    print(f"  location: {location}")
    assessment = issue.repair_assessment
    if assessment is not None:
        print(f"  safe: {str(assessment.safe).lower()}")
        print(f"  action: {assessment.action}")
        if assessment.blockers:
            for blocker in assessment.blockers:
                print(f"  blocker: {blocker}")


def _attempt_segment(attempt: PlanningAttempt, selector: str) -> Any:
    for segment in attempt.candidate.segments:
        if segment.id == selector:
            return segment
    if selector.isdigit():
        index = int(selector)
        if 0 <= index < len(attempt.candidate.segments):
            return attempt.candidate.segments[index]
    raise _CliUsageError(f"unknown attempt segment {selector!r}")


def _attempt_unit(attempt: PlanningAttempt, selector: str) -> Any:
    for unit in attempt.candidate.units:
        if unit.id == selector:
            return unit
    if selector.isdigit():
        index = int(selector)
        if 0 <= index < len(attempt.candidate.units):
            return attempt.candidate.units[index]
    raise _CliUsageError(f"unknown attempt unit {selector!r}")
