from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Literal, cast

from . import PlannerConfig, UtterancePlan, __version__
from .compiler import InputFormat, compile_document
from .config import LinguisticsConfig, PauseConfig
from .exceptions import PlanFormatError, PlanRenderabilityError, UtterPlanError
from .explain import format_explanation
from .migration import MigrationResult, migrate_plan_data

_EXAMPLES = """examples:
  utterplan compile chapter.ssmd.md
  utterplan compile chapter.ssmd.md --language de-DE
  utterplan compile plain.txt --input-format plain --language de-DE
  utterplan compile chapter.ssmd.md --json
  utterplan validate chapter.ssmd.md
  utterplan validate plain.txt --input-format plain --language de-DE
  utterplan validate chapter.utterplan.json
  utterplan inspect chapter.utterplan.json --segment 0
  utterplan explain chapter.utterplan.json
  utterplan migrate old.utterplan.json -o current.utterplan.json
  utterplan migrate old.utterplan.json --check
"""


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
    compile_parser.add_argument("--unit", choices=("paragraph", "sentence"), default="paragraph")
    compile_parser.add_argument(
        "--text-preparation",
        choices=("spokenform", "identity"),
        default="spokenform",
    )
    compile_parser.add_argument("--pause-mode", choices=("tts", "manual", "auto"), default="tts")
    compile_parser.add_argument(
        "--renderability",
        choices=("strict", "repair"),
        default="strict",
        help="reject non-renderable segments or apply safe deterministic repairs",
    )
    compile_parser.add_argument(
        "--spacy",
        choices=("auto", "off", "sm", "md", "lg", "trf"),
        default="off",
        help="linguistic-resource policy; default is the deterministic fallback",
    )
    compile_parser.add_argument("-o", "--output", type=Path, help="write the plan to this file")
    compile_parser.add_argument(
        "--force", action="store_true", help="replace an existing output file"
    )
    compile_parser.add_argument(
        "--json",
        action="store_true",
        help="also print the complete plan JSON when --output is used",
    )

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
        "migrate", help="migrate a saved plan to the current schema"
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
    inspect_parser = commands.add_parser("inspect", help="inspect a saved TTS plan")
    inspect_parser.add_argument("input", type=Path)
    inspect_parser.add_argument("--unit", type=int)
    inspect_parser.add_argument("--segment", type=int)
    inspect_parser.add_argument("--warnings", action="store_true")
    inspect_parser.add_argument("--boundaries", action="store_true")
    inspect_parser.add_argument("--tokens", action="store_true")
    inspect_parser.add_argument(
        "--semantic-boundaries",
        action="store_true",
        help="show semantic split opportunities in spoken coordinates",
    )
    inspect_parser.add_argument("--preparation", action="store_true")
    return parser


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


def _format_for_path(path: Path, source: str) -> InputFormat:
    lower_name = path.name.lower()
    if lower_name.endswith((".ssmd.md", ".ssmd")):
        return "ssmd"
    if path.suffix.lower() == ".md" and _declares_ssmd_version(source):
        return "ssmd"
    return "plain"


def _read_compile_input(args: argparse.Namespace) -> tuple[str, InputFormat]:
    if args.file is not None:
        if args.text:
            raise ValueError("--file cannot be combined with positional text")
        source = args.file.read_text(encoding="utf-8")
        input_format = (
            _format_for_path(args.file, source)
            if args.input_format == "auto"
            else _map_input_format(args.input_format)
        )
        return source, input_format

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
        if candidate.is_file():
            source = candidate.read_text(encoding="utf-8")
            input_format = (
                _format_for_path(candidate, source)
                if args.input_format == "auto"
                else _map_input_format(args.input_format)
            )
            return source, input_format

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


def _compile(args: argparse.Namespace) -> int:
    source, input_format = _read_compile_input(args)
    if args.output is not None and args.output.exists() and not args.force:
        raise ValueError(f"output exists: {args.output}; use --force to replace it")

    fallback_language = _language_fallback(source, input_format, args.language)
    config = PlannerConfig(
        language=fallback_language,
        document_format=input_format,
        text_preparation=args.text_preparation,
        unit=args.unit,
        pauses=PauseConfig(mode=args.pause_mode),
        linguistics=_linguistics_config(args.spacy),
        renderability_mode=args.renderability,
    )
    plan = compile_document(
        source,
        input_format=input_format,
        config=config,
        fallback_language=args.language,
    ).plan
    payload = plan.to_json()
    if args.output is None:
        print(payload, end="")
    else:
        args.output.write_text(payload, encoding="utf-8")
        if args.json:
            print(payload, end="")
        else:
            print(
                f"wrote {args.output} ({len(plan.segments)} segments, {len(plan.units)} units)",
                file=sys.stderr,
            )
    if args.renderability == "repair":
        planning = plan.document_metadata.get("planning", {})
        report = planning.get("renderability", {}) if isinstance(planning, dict) else {}
        repair_count = report.get("repair_count", 0) if isinstance(report, dict) else 0
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
    lines = [f"utterplan: plan is not renderable: {len(error.issues)} segments"]
    for issue in error.issues:
        if issue.line is not None and issue.column is not None:
            lines.append(f"\n{source_label}:{issue.line}:{issue.column}")
        else:
            lines.append(f"\n{source_label}: {issue.reason}")
        lines.append(f"  {issue.segment_id}  {issue.reason}")
        excerpt = issue.source_excerpt if issue.source_excerpt is not None else issue.text
        lines.append(f"  {excerpt}")
        if issue.column is not None:
            lines.append(f"  {' ' * max(0, issue.column - 1)}^")
        lines.append(f"  spoken: {issue.spoken_start}:{issue.spoken_end}")
        if issue.structural_start is not None and issue.structural_end is not None:
            lines.append(f"  structural: {issue.structural_start}:{issue.structural_end}")
    if error.issues and error.issues[0].hint:
        lines.append(f"\nHint: {error.issues[0].hint}")
    return "\n".join(lines)


def _migration_result(path: Path) -> MigrationResult:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
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
    payload = (
        json.dumps(result.data, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    )
    if args.output is None:
        print(payload, end="")
    else:
        if args.output.exists() and not args.force:
            raise ValueError(f"output exists: {args.output}; use --force to replace it")
        args.output.write_text(payload, encoding="utf-8")
        print(
            f"migrated {args.input} (schema {result.source_version} -> {result.target_version})",
            file=sys.stderr,
        )
    return 0


def _is_saved_plan(path: Path, source: str) -> bool:
    if path.suffix.lower() in {".json", ".utterplan"}:
        return True
    try:
        value = json.loads(source)
    except json.JSONDecodeError:
        return False
    return isinstance(value, dict) and value.get("format") == "utterplan"


def _validate(args: argparse.Namespace) -> int:
    path: Path = args.input
    source = path.read_text(encoding="utf-8")
    if args.input_format == "auto" and _is_saved_plan(path, source):
        result = _migration_result(path)
        plan = UtterancePlan.from_dict(result.data)
        print("valid")
        print(f"source schema version: {result.source_version}")
        print(f"current schema version: {plan.schema_version}")
        print(f"migration required: {'yes' if result.changed else 'no'}")
        print(f"plan ID: {plan.plan_id}")
        print(f"segments: {len(plan.segments)}")
        print(f"units: {len(plan.units)}")
        print(f"warnings: {len(plan.warnings)}")
        return 0

    input_format = (
        _format_for_path(path, source)
        if args.input_format == "auto"
        else _map_input_format(args.input_format)
    )
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
    print(f"segments: {len(compile_result.plan.segments)}")
    print(f"units: {len(compile_result.plan.units)}")
    print(f"warnings: {len(compile_result.plan.warnings)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "compile":
            return _compile(args)
        if args.command == "migrate":
            return _migrate(args)
        if args.command == "validate":
            return _validate(args)
        plan = UtterancePlan.load(args.input)
        if args.command == "explain":
            print(format_explanation(plan, details=args.details), end="")
            return 0
        _inspect(plan, args)
        return 0
    except PlanRenderabilityError as exc:
        print(_format_renderability_error(exc, args), file=sys.stderr)
        return 1
    except (OSError, UtterPlanError, ValueError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _inspect(plan: UtterancePlan, args: argparse.Namespace) -> None:
    print(f"Default language: {plan.config.get('language', '')}")
    print("\nTexts")
    print(f"  source:      {len(plan.source.text)} characters")
    print(f"  structural:  {len(plan.texts.structural)} characters")
    print(f"  spoken:      {len(plan.texts.spoken)} characters")
    print(f"\nUnits:     {len(plan.units)}")
    print(f"Segments:  {len(plan.segments)}")
    print(f"Languages: {len(plan.languages)}")
    print(f"Warnings:  {len(plan.warnings)}")
    if args.warnings:
        for warning in plan.warnings:
            print(f"warning: {warning}")
    if args.preparation:
        preparation = plan.preparation
        version = f" {preparation.version}" if preparation.version else ""
        print("\nPreparation")
        print(f"  backend: {preparation.backend}{version}")
        print(f"  source: {len(plan.texts.structural)} characters")
        print(f"  spoken: {len(plan.texts.spoken)} characters")
        print(f"  replacements: {len(preparation.replacements)}")
        for replacement in preparation.replacements:
            source_range = (
                f"{replacement.get('source_start', 0)}:{replacement.get('source_end', 0)}"
            )
            output_range = (
                f"{replacement.get('output_start', 0)}:{replacement.get('output_end', 0)}"
            )
            label = replacement.get("rule") or replacement.get("kind", "")
            print(f"  {source_range} -> {output_range} {label}")
            print(
                f"    {replacement.get('source', '')!r} -> {replacement.get('replacement', '')!r}"
            )
    if args.boundaries:
        print("\nBoundary events")
        for boundary in plan.boundaries:
            print(
                f"  {boundary.id}: {boundary.kind} at {boundary.position}, "
                f"{boundary.seconds}s, {boundary.origin}"
            )
    if args.semantic_boundaries:
        print("\nSemantic boundaries (spoken coordinates)")
        if not plan.semantic_boundaries:
            print("  None.")
        for boundary in plan.semantic_boundaries:
            run_id = boundary.language_run_id or "-"
            print(
                f"  {boundary.id}  {boundary.position:>6}  {boundary.kind:<14} "
                f"{boundary.origin}  run={run_id}"
            )
    if args.tokens:
        print("\nTokens")
        if plan.linguistic_runs:
            for linguistic_run in plan.linguistic_runs:
                model = linguistic_run.model or "-"
                print(f"  provider: {linguistic_run.provider}, model={model}")
        else:
            print("  provider: unknown, model=-")
        for index, token in enumerate(plan.tokens):
            token_id = token.id or f"token-{index}"
            print(
                f"  {token_id}  {token.spoken_start}:{token.spoken_end}  {token.text!r}  "
                f"lang={token.language or '-'}  lemma={token.lemma or '-'}  "
                f"pos={token.pos or '-'}  tag={token.tag or '-'}  morph={token.morph or '-'}"
            )
    if args.unit is not None:
        unit = plan.units[args.unit]
        print(f"\nUnit {unit.index}: {unit.kind} {unit.spoken_start}:{unit.spoken_end}")
        for segment_id in unit.segment_ids:
            print(f"  {segment_id}")
    if args.segment is not None:
        segment = plan.segments[args.segment]
        print(f"\nSegment {args.segment}")
        print(f"  text:          {segment.text!r}")
        print(f"  language:      {segment.language}")
        print(f"  paragraph:     {segment.paragraph}")
        print(f"  sentence:      {segment.sentence}")
        print(f"  clause:        {segment.clause}")
        print(f"  pause_before:  {segment.pause_before.seconds}s {segment.pause_before.events}")
        print(f"  pause_after:   {segment.pause_after.seconds}s {segment.pause_after.events}")
        print(f"  directives:    {segment.directives.to_dict()}")
