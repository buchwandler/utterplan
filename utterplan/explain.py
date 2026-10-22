from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Literal

from .compiler import PreparationTrace
from .model import (
    AudioDirective,
    FlowPlan,
    LegacyFlowPlan,
    LegacyPause,
    LegacyPauseKind,
    PauseIntent,
    PronunciationDirective,
    SegmentDirectives,
    VoiceDirective,
)


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _count(value: int, singular: str, plural: str | None = None) -> str:
    return f"{value} {singular if value == 1 else plural or singular + 's'}"


def format_explanation(
    plan: FlowPlan,
    *,
    details: bool = False,
    trace: PreparationTrace | None = None,
) -> str:
    """Explain executable v7 flow, source provenance, and compiler details when a trace is supplied."""
    lines = ["UtterPlan explanation", "", "Plan"]
    lines.append(f"  schema: {plan.schema_version}")
    lines.append(f"  default language: {plan.language}")
    if isinstance(plan, LegacyFlowPlan):
        lines.append(f"  historical grouping: {plan.unit}")
    else:
        lines.append("  grouping: paragraph-local")
    lines.append(
        f"  result: {_count(len(plan.flow), 'flow block')}, {_count(_flow_segment_count(plan), 'segment')}"
    )
    lines.append(f"  document format: {plan.document.format or 'unknown'}")
    if plan.document.title:
        lines.append(f"  title: {_quote(plan.document.title)}")
    if plan.source is not None:
        lines.extend(
            [
                "Source record",
                f"  format: {plan.source.format}",
                f"  sha256: {plan.source.sha256}",
            ]
        )
        if details:
            lines.append(f"  raw source: {_quote(plan.source.text)}")
        lines.append("")
    if details:
        lines.append(f"  plan id: {plan.plan_id}")
        producer = plan.producer
        producer_name = producer.get("name", "") if isinstance(producer, Mapping) else ""
        producer_version = producer.get("version") if isinstance(producer, Mapping) else None
        producer_text = f"{producer_name} {producer_version}".strip()
        lines.append(f"  producer: {producer_text or '-'}")
    lines.append("")

    if plan.document.semantics and details:
        lines.extend(["Document semantics", f"  {_json(plan.document.semantics)}", ""])
    if plan.linguistics:
        lines.append("Linguistic provenance")
        for item in plan.linguistics:
            model = f", model={item.model}" if item.model else ""
            lines.append(f"  {item.language}: {item.provider}{model}")
        lines.append("")

    lines.append("Speech plan")
    for unit_index, unit in enumerate(plan.flow, start=1):
        lines.append(f"  Unit {unit_index}")
        for segment_index, segment in enumerate(unit.segments, start=1):
            lines.append(f"    {segment_index}. [{segment.language}] {_quote(segment.text)}")
            if segment.replacements:
                lines.append("       replacements:")
                for replacement in segment.replacements:
                    lines.append(
                        f"         [{replacement.start}:{replacement.end}] "
                        f"{_quote(replacement.surface(segment.text))} <- "
                        f"{_quote(replacement.source)}"
                    )
                    metadata = [
                        f"kind={replacement.kind}" if replacement.kind else "",
                        f"rule={replacement.rule}" if replacement.rule else "",
                    ]
                    metadata = [item for item in metadata if item]
                    if metadata:
                        lines[-1] += f" ({', '.join(metadata)})"
            if segment.heading is not None:
                lines.append(f"       heading: level {segment.heading}")
            if segment.markers:
                lines.append(f"       markers: {', '.join('@' + name for name in segment.markers)}")
            lines.extend(_format_pause(segment.pause_before, edge="before"))
            lines.extend(_format_directives(segment.directives))
            lines.extend(_format_pause(segment.pause_after, edge="after"))
            if details:
                lines.append(f"       local tokens: {len(segment.tokens)}")
                for token in segment.tokens:
                    surface = segment.text[token.start : token.end]
                    lines.append(
                        f"         {token.start}:{token.end} {_quote(surface)}  "
                        f"lemma={token.lemma or '-'} pos={token.pos or '-'} "
                        f"tag={token.tag or '-'} morph={token.morph or '-'}"
                    )
        if details:
            lines.append(f"    flow hash: {unit.content_hash}")
        lines.append("")

    if plan.warnings:
        lines.append("Warnings")
        lines.extend(f"  - {warning}" for warning in plan.warnings)
        lines.append("")
    else:
        lines.extend(["No warnings.", ""])

    if trace is None:
        lines.append(
            "Compiler provenance is not stored in the plan; supply a trace sidecar for details."
        )
        return "\n".join(lines).rstrip() + "\n"

    if trace.warnings:
        lines.append("Compiler warnings")
        lines.extend(f"  - {warning}" for warning in trace.warnings)
        lines.append("")
    if trace.diagnostics:
        lines.append("Diagnostics")
        for diagnostic in trace.diagnostics:
            location = (
                f" at line {diagnostic.line}, column {diagnostic.column}"
                if diagnostic.line is not None
                else ""
            )
            if diagnostic.path:
                location += f" ({diagnostic.path})"
            lines.append(
                f"  {diagnostic.code} [{diagnostic.severity}]{location}: {diagnostic.message}"
            )
        lines.append("")
    if details:
        preparation = trace.compiler_plan.get("preparation", {})
        preparation = preparation if isinstance(preparation, Mapping) else {}
        replacements = preparation.get("replacements", [])
        replacement_count = len(replacements) if isinstance(replacements, list) else 0
        lines.extend(
            [
                "Preparation trace",
                f"  backend: {preparation.get('backend', 'unknown')}",
                f"  replacements: {replacement_count}",
                f"  structural characters: {len(trace.structural_text)}",
                f"  spoken characters: {len(trace.spoken_text)}",
            ]
        )
        for trace_unit in trace.units:
            for change in trace_unit.transformations:
                source_range = (
                    f"{change.source_start}:{change.source_end}"
                    if change.source_start is not None and change.source_end is not None
                    else "unknown"
                )
                output_range = (
                    f"{change.output_start}:{change.output_end}"
                    if change.output_start is not None and change.output_end is not None
                    else "unknown"
                )
                lines.append(
                    f"  {source_range} {_quote(change.source or '')} -> "
                    f"{output_range} {_quote(change.replacement or '')} "
                    f"({change.rule or change.kind or 'preparation'})"
                )
        lines.extend(
            [
                "",
                "Compiler trace",
                f"  source hash: {trace.source_sha256}",
                f"  boundary events: {len(trace.compiler_plan.get('boundaries', []))}",
                f"  repairs: {len(trace.repairs)}",
                "",
            ]
        )
        semantic_boundaries = trace.compiler_plan.get("semantic_boundaries", [])
        if isinstance(semantic_boundaries, (list, tuple)):
            for boundary in semantic_boundaries:
                if not isinstance(boundary, Mapping):
                    continue
                kind = boundary.get("kind")
                position = boundary.get("position")
                if isinstance(kind, str) and type(position) is int:
                    lines.append(f"Semantic boundary: {kind} at spoken offset {position}")
    return "\n".join(lines).rstrip() + "\n"


def _flow_segment_count(plan: FlowPlan) -> int:
    return sum(len(unit.segments) for unit in plan.flow)


def _format_pause(
    pause: PauseIntent | LegacyPause | LegacyPauseKind | None, *, edge: Literal["before", "after"]
) -> list[str]:
    if pause is None:
        return []
    if isinstance(pause, LegacyPause):
        if pause.seconds == 0 and not pause.events:
            return []
        return [f"       {edge}: legacy pause {pause.seconds:g}s"]
    value = (
        f"timed {pause.time}"
        if isinstance(pause, PauseIntent) and pause.type == "timed"
        else pause.type
    )
    return [f"       {edge}: pause {value}"]


def _format_directives(directives: SegmentDirectives) -> list[str]:
    result: list[str] = []
    if directives.voice is not None:
        result.append(f"       voice: {_format_voice(directives.voice)}")
    if directives.pronunciation is not None:
        result.append(f"       pronunciation: {_format_pronunciation(directives.pronunciation)}")
    if directives.prosody is not None:
        values = []
        for label, value in (
            ("rate", directives.prosody.rate),
            ("pitch", directives.prosody.pitch),
            ("volume", directives.prosody.volume),
        ):
            if value is not None:
                values.append(f"{label} {value}")
        if values:
            result.append(f"       effective prosody: {', '.join(values)}")
    if directives.emphasis is not None:
        result.append(f"       emphasis: {directives.emphasis.level}")
    if directives.say_as is not None:
        values = [directives.say_as.interpret_as]
        if directives.say_as.format is not None:
            values.append(f"format {directives.say_as.format}")
        if directives.say_as.detail is not None:
            values.append(f"detail {directives.say_as.detail}")
        result.append(f"       say-as: {', '.join(values)}")
    if directives.substitution is not None:
        result.append(f"       substitution: {_quote(directives.substitution.alias)}")
    if directives.audio is not None:
        result.append(f"       audio: {_format_audio(directives.audio)}")
    if directives.extensions:
        names = ", ".join(item.name for item in directives.extensions)
        result.append(f"       extension refs: {names}")
    return result


def _format_voice(directive: VoiceDirective) -> str:
    values = (
        ("reference", directive.reference),
        ("name", directive.name),
        ("languages", directive.languages),
        ("gender", directive.gender),
        ("age", directive.age),
        ("variant", directive.variant),
    )
    return ", ".join(f"{name}={value}" for name, value in values if value is not None)


def _format_pronunciation(directive: PronunciationDirective) -> str:
    return f"/{directive.phonemes}/ ({directive.alphabet})"


def _format_audio(directive: AudioDirective) -> str:
    values = [f"src {_quote(directive.src)}"]
    if directive.description is not None:
        values.append(f"description {_quote(directive.description)}")
    if directive.alt_text is not None:
        values.append(f"legacy alt text {_quote(directive.alt_text)}")
    if directive.clip_begin is not None or directive.clip_end is not None:
        values.append(f"clip {directive.clip_begin or ''}..{directive.clip_end or ''}")
    if directive.speed is not None:
        values.append(f"speed {directive.speed}")
    if directive.repeat_duration is not None:
        values.append(f"repeat duration {directive.repeat_duration}")
    if directive.repeat_count is not None:
        values.append(f"repeat count {directive.repeat_count:g}")
    if directive.sound_level is not None:
        values.append(f"level {directive.sound_level}")
    return ", ".join(values)


def _json(value: object, *, indent: int | None = None) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent)
