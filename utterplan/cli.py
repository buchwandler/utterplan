from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Literal, cast

from . import PlannerConfig, UtterancePlan, UtterancePlanner, __version__
from .config import LinguisticsConfig, PauseConfig
from .exceptions import PlanFormatError, UtterPlanError
from .explain import format_explanation
from .migration import MigrationResult, migrate_plan_data

InputFormat = Literal["plain", "ssmd"]


_EXAMPLES = """examples:
  utterplan compile "Hello world." --lang en-us
  echo "Hello world." | utterplan compile --lang en-us | jq .
  utterplan compile chapter.ssmd --lang en-us -o chapter.utterplan.json
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
    compile_parser.add_argument("--language", "--lang", required=True, dest="language")
    compile_parser.add_argument(
        "--input-format",
        "--format",
        dest="input_format",
        choices=("auto", "text", "ssmd"),
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

    validate_parser = commands.add_parser("validate", help="validate a saved TTS plan")
    validate_parser.add_argument("input", type=Path)

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

    if args.input_format == "text":
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
    if value == "text":
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

    config = PlannerConfig(
        language=args.language,
        document_format=input_format,
        text_preparation=args.text_preparation,
        unit=args.unit,
        pauses=PauseConfig(mode=args.pause_mode),
        linguistics=_linguistics_config(args.spacy),
    )
    plan = UtterancePlanner(config).plan(source)
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
    return 0


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


def _validate(path: Path) -> int:
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "compile":
            return _compile(args)
        if args.command == "migrate":
            return _migrate(args)
        if args.command == "validate":
            return _validate(args.input)
        plan = UtterancePlan.load(args.input)
        if args.command == "explain":
            print(format_explanation(plan, details=args.details), end="")
            return 0
        _inspect(plan, args)
        return 0
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
        print("\nBoundaries")
        for boundary in plan.boundaries:
            print(
                f"  {boundary.id}: {boundary.kind} at {boundary.position}, "
                f"{boundary.seconds}s, {boundary.origin}"
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
