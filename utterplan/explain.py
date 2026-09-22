from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Literal

from .model import (
    AudioDirective,
    BoundaryEvent,
    Marker,
    PlanSegment,
    PlanUnit,
    PronunciationDirective,
    ResolvedPause,
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


def _format_seconds(seconds: float) -> str:
    return f"{seconds:.2f} s"


def format_explanation(plan: UtterancePlan, *, details: bool = False) -> str:
    """Return a deterministic, human-oriented explanation of a compiled plan."""
    lines = ["UtterPlan explanation", ""]
    _format_plan_summary(plan, lines, details=details)
    _format_preparation(plan, lines, details=details)
    _format_speech_plan(plan, lines, details=details)
    if details:
        _format_language_runs(plan, lines)
        _format_metadata(plan, lines)
        _format_diagnostics(plan, lines)
    _format_warnings(plan, lines)
    return "\n".join(lines).rstrip() + "\n"


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
    result.extend(
        _format_pause(segment.pause_before, boundaries_by_id, edge="before", details=details)
    )
    result.extend(_format_directives(segment.directives))
    result.extend(
        _format_pause(segment.pause_after, boundaries_by_id, edge="after", details=details)
    )
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
    pause: ResolvedPause,
    boundaries_by_id: Mapping[str, BoundaryEvent],
    *,
    edge: Literal["before", "after"],
    details: bool,
) -> list[str]:
    if not pause.events and pause.seconds == 0:
        return []
    causes = []
    for event_id in pause.events:
        boundary = boundaries_by_id.get(event_id)
        cause = _boundary_description(boundary) if boundary is not None else f"boundary {event_id}"
        if cause not in causes:
            causes.append(cause)
    description = " + ".join(causes)
    line = f"       {edge}: pause {_format_seconds(pause.seconds)}"
    if description:
        line += f": {description}"
    result = [line]
    if details and pause.events:
        result.append(f"         events: {', '.join(pause.events)}")
        for event_id in pause.events:
            boundary = boundaries_by_id.get(event_id)
            if boundary is None:
                continue
            strength = f", strength {boundary.strength}" if boundary.strength else ""
            attrs = f", attrs {_json(boundary.attrs)}" if boundary.attrs else ""
            result.append(
                f"         boundary {boundary.id}: kind {boundary.kind}, "
                f"origin {boundary.origin}{strength}{attrs}"
            )
    return result


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
            result.append(f"       prosody: {', '.join(values)}")
    if directives.emphasis is not None:
        result.append(f"       emphasis: {directives.emphasis.level}")
    if directives.audio is not None:
        result.append(f"       audio: {_format_audio(directives.audio)}")
    return result


def _format_voice(directive: VoiceDirective) -> str:
    return directive.reference


def _format_pronunciation(directive: PronunciationDirective) -> str:
    return f"/{directive.phonemes}/ ({directive.alphabet})"


def _format_audio(directive: AudioDirective) -> str:
    result = _quote(directive.src)
    if directive.clip_begin is not None or directive.clip_end is not None:
        result += f" (clip {directive.clip_begin or ''}..{directive.clip_end or ''}"
        if directive.speed is not None:
            result += f", speed {directive.speed}"
        result += ")"
    elif directive.speed is not None:
        result += f" (speed {directive.speed})"
    return result


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
    lines.append("Document metadata")
    if plan.document_metadata:
        lines.extend(f"  {line}" for line in _json(plan.document_metadata, indent=2).splitlines())
    else:
        lines.append("  None.")
    lines.append("")


def _format_diagnostics(plan: UtterancePlan, lines: list[str]) -> None:
    lines.append("Diagnostics")
    if not plan.diagnostics:
        lines.append("  None.")
    else:
        for diagnostic in plan.diagnostics:
            location = f" ({diagnostic.path})" if diagnostic.path else ""
            lines.append(
                f"  {diagnostic.code} [{diagnostic.severity}]{location}: {diagnostic.message}"
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
