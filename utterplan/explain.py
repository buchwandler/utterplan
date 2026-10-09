from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Literal

from .compiler import PreparationTrace
from .model import (
    AudioDirective,
    BoundaryEvent,
    FlowPlan,
    LegacyPause,
    Marker,
    PauseIntent,
    PlanSegment,
    PlanUnit,
    PronunciationDirective,
    SegmentDirectives,
    UtterancePlan,
    VoiceDirective,
)

_BOUNDARY_KINDS = {
    "sentence": "sentence boundary",
    "paragraph": "paragraph boundary",
    "parenthetical": "parenthetical boundary",
    "clausal_comma": "clause boundary",
    "voice_change": "voice change",
    "explicit": "explicit boundary",
}
_ORIGINS = {
    "ssmd": "from SSMD",
    "phrasplit": "detected by phrasplit",
    "planner": "automatic planner",
    "plain": "from plain-text structure",
}


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _count(value: int, singular: str, plural: str | None = None) -> str:
    return f"{value} {singular if value == 1 else plural or singular + 's'}"


def _replacement_count(plan: UtterancePlan) -> str:
    count = len(plan.preparation.replacements)
    return "no replacements" if count == 0 else _count(count, "replacement", "replacements")


def format_explanation(
    plan: FlowPlan,
    *,
    details: bool = False,
    trace: PreparationTrace | None = None,
) -> str:
    """Explain executable v5 flow, with compiler provenance only when trace is supplied."""
    lines = ["UtterPlan explanation", "", "Plan"]
    lines.append(f"  schema: {plan.schema_version}")
    lines.append(f"  default language: {plan.language}")
    lines.append(f"  grouping: {plan.unit}")
    lines.append(
        f"  result: {_count(len(plan.flow), 'unit')}, {_count(_flow_segment_count(plan), 'segment')}"
    )
    lines.append(f"  document format: {plan.document.format or 'unknown'}")
    if plan.document.title:
        lines.append(f"  title: {_quote(plan.document.title)}")
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


def _format_plan_summary(plan: UtterancePlan, lines: list[str], *, details: bool) -> None:
    config = plan.config
    pauses = config.get("pauses", {})
    pause_mode = pauses.get("mode", "") if isinstance(pauses, Mapping) else ""
    lines.extend(
        [
            "Plan",
            f"  input: {plan.source.format}",
            f"  default language: {config.get('language', '')}",
            f"  preparation: {plan.preparation.backend}, {_replacement_count(plan)}",
            f"  pause mode: {pause_mode}",
            f"  grouping: {config.get('unit', '')}",
            f"  result: {_count(len(plan.units), 'unit')}, {_count(len(plan.segments), 'segment')}",
            "",
        ]
    )
    if plan.source.format == "ssmd":
        metadata = plan.document_metadata
        summary: list[str] = []
        if version := metadata.get("ssmd_version"):
            summary.append(f"  SSMD version: {version}")
        if title := metadata.get("title"):
            summary.append(f"  title: {_quote(str(title))}")
        if language := metadata.get("language"):
            summary.append(f"  document language: {language}")
        if summary:
            lines[-1:-1] = summary
    if not details:
        return

    producer = plan.producer
    producer_name = producer.get("name", "") if isinstance(producer, Mapping) else ""
    producer_version = producer.get("version") if isinstance(producer, Mapping) else None
    producer_text = str(producer_name)
    if producer_version:
        producer_text = f"{producer_text} {producer_version}"
    lines.extend(
        [
            "Details",
            f"  format: {plan.format}",
            f"  schema: {plan.schema_version}",
            f"  producer: {producer_text}",
            f"  plan id: {plan.plan_id}",
            f"  structural text: {len(plan.texts.structural)} characters",
            f"  spoken text: {len(plan.texts.spoken)} characters",
            f"  language runs: {len(plan.languages)}",
            f"  annotations: {len(plan.annotations)}",
            f"  boundaries: {len(plan.boundaries)}",
            f"  semantic boundaries: {len(plan.semantic_boundaries)}",
            f"  tokens: {len(plan.tokens)}",
            f"  markers: {len(plan.markers)}",
            "",
        ]
    )


def _format_preparation(plan: UtterancePlan, lines: list[str], *, details: bool) -> None:
    replacements = plan.preparation.replacements
    lines.extend(["Text preparation"])
    if not replacements:
        lines.append("  No written-to-spoken changes.")
        lines.append("")
        return

    lines.append(f"  {_count(len(replacements), 'change', 'changes')}:")
    for replacement in replacements:
        source = str(replacement.get("source", ""))
        replacement_text = str(replacement.get("replacement", ""))
        label = _replacement_label(replacement)
        suffix = f"  ({label})" if label else ""
        lines.append(f"    {_quote(source)} -> {_quote(replacement_text)}{suffix}")
        if details:
            lines.append(
                "      structural "
                f"{replacement.get('source_start', 0)}:{replacement.get('source_end', 0)}"
                " -> spoken "
                f"{replacement.get('output_start', 0)}:{replacement.get('output_end', 0)}"
            )
    lines.append("")


def _replacement_label(replacement: Mapping[str, object]) -> str:
    kind = replacement.get("kind")
    rule = replacement.get("rule")
    if kind and rule and str(kind) != str(rule):
        return f"{kind}: {rule}"
    if rule:
        return str(rule)
    if kind:
        return str(kind)
    return ""


def _format_heading_events(plan: UtterancePlan, lines: list[str]) -> None:
    headings = [boundary for boundary in plan.boundaries if boundary.kind == "heading"]
    if not headings:
        return

    lines.append("Structural events")
    for boundary in headings:
        level = boundary.attrs.get("level", "?")
        lines.append(f"  heading level {level} at spoken {boundary.position}")
    lines.append("")


def _format_semantic_boundaries(plan: UtterancePlan, lines: list[str], *, details: bool) -> None:
    if not plan.semantic_boundaries:
        return
    lines.append("Semantic boundaries (spoken coordinates)")
    for boundary in plan.semantic_boundaries:
        origin = _ORIGINS.get(boundary.origin, boundary.origin)
        lines.append(
            f"  Semantic boundary: {boundary.kind} at spoken offset {boundary.position} ({origin})"
        )
        if details:
            lines.append(f"    id: {boundary.id}")
            if boundary.language_run_id is not None:
                lines.append(f"    language run: {boundary.language_run_id}")
            if boundary.attrs:
                lines.append(f"    attrs: {_json(boundary.attrs)}")
    lines.append("")


def _format_speech_plan(plan: UtterancePlan, lines: list[str], *, details: bool) -> None:
    segments_by_id = {segment.id: segment for segment in plan.segments}
    markers_by_id = {marker.id: marker for marker in plan.markers}
    boundaries_by_id = {boundary.id: boundary for boundary in plan.boundaries}
    lines.extend(["Speech plan"])
    for number, unit in enumerate(plan.units, start=1):
        lines.append(f"  Unit {number}: {unit.kind}")
        _format_markers(unit, markers_by_id, lines, details=details)
        for segment_number, segment_id in enumerate(unit.segment_ids, start=1):
            segment = segments_by_id[segment_id]
            formatted_segment = _format_segment(
                segment,
                segment_number,
                boundaries_by_id,
                details=details,
            )
            lines.extend(formatted_segment)
            if details:
                lines.extend(_format_segment_tokens(plan, segment))
        if details:
            lines.append(f"    id: {unit.id}")
            lines.append(f"    spoken: {unit.spoken_start}:{unit.spoken_end}")
            lines.append(f"    content hash: {unit.content_hash}")
        lines.append("")


def _format_markers(
    unit: PlanUnit,
    markers_by_id: Mapping[str, Marker],
    lines: list[str],
    *,
    details: bool,
) -> None:
    markers = [markers_by_id[marker_id] for marker_id in unit.marker_ids]
    if not markers:
        return
    if not details:
        names = ", ".join(f"@{marker.name}" for marker in markers)
        lines.append(f"    markers: {names}")
        return
    lines.append("    markers:")
    for marker in markers:
        attrs = f" {_json(marker.attrs)}" if marker.attrs else ""
        lines.append(
            f"      @{marker.name} at spoken {marker.spoken_position} ({marker.id}){attrs}"
        )


def _format_segment(
    segment: PlanSegment,
    number: int,
    boundaries_by_id: Mapping[str, BoundaryEvent],
    *,
    details: bool,
) -> list[str]:
    result = [f"    {number}. [{segment.language}] {_quote(segment.text)}"]
    result.extend(_format_pause(segment.pause_before, edge="before"))
    result.extend(_format_directives(segment.directives))
    result.extend(_format_pause(segment.pause_after, edge="after"))
    if details:
        result.extend(
            [
                f"       id: {segment.id}",
                f"       spoken: {segment.spoken_start}:{segment.spoken_end}",
                f"       structure: paragraph {segment.paragraph}, "
                f"sentence {segment.sentence}, clause {segment.clause}",
                f"       tokens: {len(segment.token_indices)}",
                f"       annotations: {', '.join(segment.annotation_ids) if segment.annotation_ids else 'none'}",
            ]
        )
        if segment.structural_start is not None and segment.structural_end is not None:
            result.append(f"       structural: {segment.structural_start}:{segment.structural_end}")
    return result


def _format_segment_tokens(plan: UtterancePlan, segment: PlanSegment) -> list[str]:
    if not segment.token_indices:
        return ["       tokens: none"]
    lines = ["       tokens:"]
    for index in segment.token_indices:
        token = plan.tokens[index]
        lines.append(
            f"         {_quote(token.text)}  lang={token.language or '-'}  "
            f"lemma={token.lemma or '-'}  pos={token.pos or '-'}  "
            f"tag={token.tag or '-'}  morph={token.morph or '-'}"
        )
    return lines


def _format_pause(
    pause: PauseIntent | LegacyPause | None, *, edge: Literal["before", "after"]
) -> list[str]:
    if pause is None:
        return []
    if isinstance(pause, LegacyPause):
        if pause.seconds == 0 and not pause.events:
            return []
        return [f"       {edge}: legacy pause {pause.seconds:g}s"]
    value = f"timed {pause.time}" if pause.type == "timed" else pause.type
    return [f"       {edge}: pause {value}"]


def _boundary_description(boundary: BoundaryEvent) -> str:
    detected_kind = boundary.attrs.get("detected_kind")
    if detected_kind == "parenthetical_open":
        label = "parenthetical opening"
    elif detected_kind == "parenthetical_close":
        label = "parenthetical closing"
    else:
        label = _BOUNDARY_KINDS.get(boundary.kind, f'boundary "{boundary.kind}"')
    origin = _ORIGINS.get(boundary.origin)
    return f"{label}, {origin}" if origin else label


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


def _format_language_runs(plan: UtterancePlan, lines: list[str]) -> None:
    lines.extend(["Language runs"])
    analysis_by_language = {item.language_run_id: item for item in plan.linguistic_runs}
    if not plan.languages:
        lines.append("  None.")
    else:
        for run in plan.languages:
            analysis = analysis_by_language.get(run.id)
            if analysis is None:
                provider = "unknown"
                model = "-"
            else:
                provider = analysis.provider
                model = analysis.model or "-"
            lines.append(
                f"  {run.language}  spoken {run.spoken_start}:{run.spoken_end}"
                f"  source: {run.source}"
            )
            lines.append(f"    analysis: provider={provider}, model={model}")
    lines.append("")


def _format_metadata(plan: UtterancePlan, lines: list[str]) -> None:
    metadata = plan.document_metadata
    displayed: list[str] = []
    bindings = metadata.get("voice_bindings")
    if isinstance(bindings, Mapping) and bindings:
        binding_values = ", ".join(
            f"{name}={_json(value)}" for name, value in sorted(bindings.items())
        )
        displayed.append(f"  voice bindings: {binding_values}")
    defaults = metadata.get("voice_defaults")
    if isinstance(defaults, Mapping) and defaults:
        default_values = []
        for name, fields in sorted(defaults.items()):
            if isinstance(fields, Mapping):
                default_values.append(f"{name} ({_format_metadata_fields(fields)})")
        if default_values:
            displayed.append(f"  voice defaults: {', '.join(default_values)}")
    for key, label in (
        ("pause_defaults", "pause defaults"),
        ("prosody_transitions", "prosody transitions"),
        ("language_detection", "language detection"),
    ):
        value = metadata.get(key)
        if isinstance(value, Mapping) and value:
            displayed.append(f"  {label}: {_format_metadata_fields(value)}")
    requires = metadata.get("requires")
    if isinstance(requires, Mapping):
        extensions = requires.get("extensions")
        if isinstance(extensions, (list, tuple)) and extensions:
            displayed.append(f"  required extensions: {', '.join(map(str, extensions))}")
    lines.append("Document metadata")
    lines.extend(displayed or ["  No portable metadata."])
    lines.append("")


def _format_metadata_fields(values: Mapping[str, object]) -> str:
    return ", ".join(f"{key}={_json(value)}" for key, value in sorted(values.items()))


def _format_diagnostics(plan: UtterancePlan, lines: list[str]) -> None:
    lines.append("Diagnostics")
    if not plan.diagnostics:
        lines.append("  None.")
    else:
        for diagnostic in plan.diagnostics:
            locations = []
            if diagnostic.path:
                locations.append(diagnostic.path)
            if diagnostic.source_start is not None or diagnostic.source_end is not None:
                locations.append(
                    f"source {diagnostic.source_start or 0}:{diagnostic.source_end or 0}"
                )
            if diagnostic.line is not None:
                location = f"line {diagnostic.line}"
                if diagnostic.column is not None:
                    location += f", column {diagnostic.column}"
                locations.append(location)
            suffix = f" ({'; '.join(locations)})" if locations else ""
            lines.append(
                f"  {diagnostic.code} [{diagnostic.severity}]{suffix}: {diagnostic.message}"
            )
    lines.append("")


def _format_warnings(plan: UtterancePlan, lines: list[str]) -> None:
    warnings = list(plan.warnings)
    preparation_warnings = list(plan.preparation.warnings)
    if not warnings and not preparation_warnings:
        lines.append("No warnings.")
        return
    lines.append("Warnings")
    for warning in warnings:
        lines.append(f"  - {warning}")
    for warning in preparation_warnings:
        lines.append(f"  - preparation: {warning}")


def _json(value: object, *, indent: int | None = None) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent)
