from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

from .config import PauseConfig
from .exceptions import PlanRenderabilityError, PlanValidationError
from .model import (
    AnnotationSpan,
    BoundaryEvent,
    PlanSegment,
    SemanticBoundary,
    TokenAnnotation,
    UtterancePlan,
)
from .parsers import ParsedDocument, map_structural_span_to_source
from .pauses import boundary_is_active

RenderabilityMode = Literal["strict", "repair"]

RenderabilityAction = Literal["merge_previous", "merge_next", "drop", "none"]


@dataclass(frozen=True, slots=True)
class RenderabilityRepair:
    action: RenderabilityAction
    safe: bool
    blockers: tuple[str, ...] = ()
    neighbor_segment_id: str | None = None


@dataclass(frozen=True, slots=True)
class RenderabilityIssue:
    code: str
    reason: str
    segment_id: str
    segment_index: int
    text: str
    spoken_start: int
    spoken_end: int
    structural_start: int | None = None
    structural_end: int | None = None
    source_start: int | None = None
    source_end: int | None = None
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None
    source_excerpt: str | None = None
    source_context: tuple[tuple[int, str], ...] = ()
    source_caret: int | None = None
    spoken_context: str | None = None
    token_pos: tuple[str, ...] = ()
    token_ids: tuple[str, ...] = ()
    repair: str | None = None
    repair_assessment: RenderabilityRepair | None = None
    hint: str | None = None


@dataclass(frozen=True, slots=True)
class RenderabilityReport:
    checked_segments: int
    issues: tuple[RenderabilityIssue, ...]
    repairs: tuple[RenderabilityIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues


def contains_speech_content(value: str) -> bool:
    """Return whether text contains a Unicode letter or number outside whitespace."""
    for char in value:
        if char.isspace():
            continue
        category = unicodedata.category(char)
        if category.startswith(("L", "N")):
            return True
    return False


def classify_segment(
    segment: PlanSegment,
    segment_index: int,
    tokens: tuple[TokenAnnotation, ...] = (),
    *,
    parsed: ParsedDocument | None = None,
    spoken_text: str | None = None,
) -> RenderabilityIssue | None:
    """Classify one renderer segment; Unicode content is the stable base rule."""
    selected_token_pairs = tuple(
        (index, tokens[index]) for index in segment.token_indices if 0 <= index < len(tokens)
    )
    selected_tokens = tuple(token for _index, token in selected_token_pairs)
    if _has_explicit_speech_semantics(segment):
        return None
    if contains_speech_content(segment.text):
        return None

    significant = tuple(char for char in segment.text if not char.isspace())
    if not significant:
        code, reason, hint = (
            (
                "renderability.empty",
                "empty",
                "Add spoken text or an explicit whole-segment speech/media directive.",
            )
            if not segment.text
            else (
                "renderability.whitespace_only",
                "whitespace_only",
                "Replace whitespace-only content with speech or remove the renderer segment.",
            )
        )
    elif all(unicodedata.category(char).startswith("P") for char in significant):
        code = "renderability.punctuation_only"
        reason = "punctuation_only"
        hint = "Attach punctuation to spoken text or remove the isolated punctuation segment."
    elif not contains_speech_content(segment.text):
        code = "renderability.symbol_only"
        reason = "symbol_only"
        hint = 'Replace the symbol with intended spoken words, or annotate SSMD (for example, `[€]{sub="euro"}`); UtterPlan will not guess.'
    else:  # Defensive fallback should Unicode categories evolve.
        code = "renderability.no_semantic_speech"
        reason = "no_semantic_speech"
        hint = "Add ordinary speech content or an explicit whole-segment semantic directive."

    structural_start = segment.structural_start
    structural_end = segment.structural_end
    source_start: int | None = None
    source_end: int | None = None
    source_text = getattr(parsed, "source_text", None) if parsed is not None else None
    if parsed is not None and structural_start is not None and structural_end is not None:
        source_start, source_end = map_structural_span_to_source(
            parsed, structural_start, structural_end
        )
    line = column = end_line = end_column = None
    excerpt = None
    source_context: tuple[tuple[int, str], ...] = ()
    source_caret: int | None = None
    if isinstance(source_text, str) and source_start is not None:
        line, column = _line_column(source_text, source_start)
        if source_end is not None:
            end_line, end_column = _line_column(source_text, source_end)
        excerpt = _source_excerpt(source_text, source_start)
        source_context, source_caret = _source_context(source_text, source_start, source_end)
    spoken_context = (
        _spoken_context(spoken_text, segment.spoken_start, segment.spoken_end)
        if spoken_text is not None
        else None
    )
    return RenderabilityIssue(
        code=code,
        reason=reason,
        segment_id=segment.id,
        segment_index=segment_index,
        text=segment.text,
        spoken_start=segment.spoken_start,
        spoken_end=segment.spoken_end,
        structural_start=structural_start,
        structural_end=structural_end,
        source_start=source_start,
        source_end=source_end,
        line=line,
        column=column,
        end_line=end_line,
        end_column=end_column,
        source_excerpt=excerpt,
        source_context=source_context,
        source_caret=source_caret,
        spoken_context=spoken_context,
        token_pos=tuple(token.pos for token in selected_tokens if token.pos is not None),
        token_ids=tuple(
            token.id if token.id is not None else f"token-{index}"
            for index, token in selected_token_pairs
        ),
        hint=hint,
    )


def preflight_segments(
    segments: tuple[PlanSegment, ...] | list[PlanSegment],
    tokens: tuple[TokenAnnotation, ...],
    *,
    parsed: ParsedDocument | None = None,
    spoken_text: str | None = None,
    boundaries: tuple[BoundaryEvent, ...] | list[BoundaryEvent] = (),
    pause_config: PauseConfig | None = None,
    annotations: tuple[AnnotationSpan, ...] = (),
    semantic_boundaries: tuple[SemanticBoundary, ...] | list[SemanticBoundary] = (),
) -> RenderabilityReport:
    issues = tuple(
        issue
        for index, segment in enumerate(segments)
        if (
            issue := classify_segment(
                segment, index, tokens, parsed=parsed, spoken_text=spoken_text
            )
        )
        is not None
    )
    if spoken_text is not None and pause_config is not None:
        issues = tuple(
            replace(
                issue,
                repair_assessment=assess_renderability_repair(
                    issue,
                    segments[issue.segment_index],
                    segments,
                    spoken_text=spoken_text,
                    boundaries=boundaries,
                    pause_config=pause_config,
                    annotations=annotations,
                    semantic_boundaries=semantic_boundaries,
                ),
            )
            for issue in issues
        )
    repairs = tuple(
        issue
        for issue in issues
        if issue.repair_assessment is not None and issue.repair_assessment.safe
    )
    return RenderabilityReport(checked_segments=len(segments), issues=issues, repairs=repairs)


def preflight_renderability(plan: UtterancePlan) -> RenderabilityReport:
    """Inspect every renderer-facing segment in a completed plan."""
    pause_values = plan.config.get("pauses")
    pause_config = (
        PauseConfig(
            mode=pause_values.get("mode", "tts"),
            enabled=pause_values.get("enabled", True),
        )
        if isinstance(pause_values, dict)
        else PauseConfig()
    )
    return preflight_segments(
        plan.segments,
        plan.tokens,
        spoken_text=plan.texts.spoken,
        boundaries=plan.boundaries,
        pause_config=pause_config,
        annotations=plan.annotations,
        semantic_boundaries=plan.semantic_boundaries,
    )


def assess_renderability_repair(
    issue: RenderabilityIssue,
    segment: PlanSegment,
    segments: tuple[PlanSegment, ...] | list[PlanSegment],
    *,
    spoken_text: str,
    boundaries: tuple[BoundaryEvent, ...] | list[BoundaryEvent],
    pause_config: PauseConfig,
    annotations: tuple[AnnotationSpan, ...],
    semantic_boundaries: tuple[SemanticBoundary, ...] | list[SemanticBoundary],
) -> RenderabilityRepair:
    """Assess safe punctuation repairs without changing segments or boundaries."""
    if issue.code != "renderability.punctuation_only":
        return RenderabilityRepair("none", False)

    significant = [char for char in segment.text if not char.isspace()]
    terminal = bool(significant and significant[-1] in ".!?…。！？")
    directions = (-1, 1) if terminal else (1, -1)
    blockers: list[str] = []
    for direction in directions:
        neighbor_index = issue.segment_index + direction
        if not 0 <= neighbor_index < len(segments):
            side = "previous" if direction < 0 else "following"
            blockers.append(f"no {side} renderer segment is available to merge")
            continue
        neighbor = segments[neighbor_index]
        merge_blockers = _merge_punctuation_blockers(
            segment,
            neighbor,
            direction,
            spoken_text,
            boundaries,
            pause_config,
            annotations,
            semantic_boundaries,
        )
        if not merge_blockers:
            action: RenderabilityAction = "merge_previous" if direction < 0 else "merge_next"
            return RenderabilityRepair(action, True, tuple(dict.fromkeys(blockers)), neighbor.id)
        blockers.extend(merge_blockers)

    drop_blockers = _drop_punctuation_blockers(
        segment, boundaries, pause_config, annotations, semantic_boundaries
    )
    if not drop_blockers:
        return RenderabilityRepair("drop", True, tuple(dict.fromkeys(blockers)))
    blockers.extend(drop_blockers)
    return RenderabilityRepair("none", False, tuple(dict.fromkeys(blockers)))


def _merge_punctuation_blockers(
    punctuation: PlanSegment,
    neighbor: PlanSegment,
    direction: int,
    text: str,
    boundaries: tuple[BoundaryEvent, ...] | list[BoundaryEvent],
    pause_config: PauseConfig,
    annotations: tuple[AnnotationSpan, ...],
    semantic_boundaries: tuple[SemanticBoundary, ...] | list[SemanticBoundary],
) -> tuple[str, ...]:
    blockers: list[str] = []
    if not _is_neutral_punctuation_text(punctuation.text):
        blockers.append("punctuation is not neutral punctuation")
    if not contains_speech_content(neighbor.text):
        blockers.append("adjacent segment has no semantic speech content")
    if punctuation.language != neighbor.language:
        blockers.append(f"language changes from {punctuation.language} to {neighbor.language}")
    if punctuation.paragraph != neighbor.paragraph:
        blockers.append("merge would cross a paragraph boundary")
    if punctuation.directives.to_dict():
        blockers.append("semantic directive belongs to the punctuation segment")
    if punctuation.directives != neighbor.directives:
        blockers.append("segment directives differ across the join")

    if direction < 0:
        gap_start, gap_end = neighbor.spoken_end, punctuation.spoken_start
    else:
        gap_start, gap_end = punctuation.spoken_end, neighbor.spoken_start
    if gap_start > gap_end or text[gap_start:gap_end].strip():
        blockers.append("spoken text separates the punctuation from adjacent speech")
    for boundary in boundaries:
        if (
            gap_start <= boundary.position <= gap_end
            or punctuation.spoken_start < boundary.position < punctuation.spoken_end
        ) and boundary_is_active(boundary, pause_config):
            blockers.append(f"active pause at spoken position {boundary.position}")
    for annotation in annotations:
        if _audio_annotation(annotation) and _annotation_overlaps_segment(annotation, punctuation):
            blockers.append("audio/media occurrence overlaps the punctuation segment")
    audio_blocker = _audio_join_blocker(gap_start, gap_end, annotations)
    if audio_blocker is not None:
        blockers.append(audio_blocker)
    for semantic_boundary in semantic_boundaries:
        if (
            gap_start < semantic_boundary.position < gap_end
            or punctuation.spoken_start < semantic_boundary.position < punctuation.spoken_end
        ):
            blockers.append(
                f"{semantic_boundary.kind} semantic boundary at spoken position {semantic_boundary.position}"
            )
    for annotation in annotations:
        if (
            _language_annotation(annotation)
            or _audio_annotation(annotation)
            or not _semantic_annotation(annotation)
        ):
            continue
        tag = str(annotation.attrs.get("tag") or annotation.kind).lower().replace("_", "-")
        if _annotation_overlaps_segment(annotation, punctuation):
            blockers.append(f"{tag} annotation belongs to the punctuation segment")
        elif any(
            position is not None and gap_start <= position <= gap_end
            for position in (annotation.spoken_start, annotation.spoken_end)
        ):
            blockers.append(f"{tag} annotation crosses the join")
    return tuple(dict.fromkeys(blockers))


def _drop_punctuation_blockers(
    segment: PlanSegment,
    boundaries: tuple[BoundaryEvent, ...] | list[BoundaryEvent],
    pause_config: PauseConfig,
    annotations: tuple[AnnotationSpan, ...],
    semantic_boundaries: tuple[SemanticBoundary, ...] | list[SemanticBoundary],
) -> tuple[str, ...]:
    blockers: list[str] = []
    if not _is_neutral_punctuation_text(segment.text):
        blockers.append("punctuation is not neutral punctuation")
    for name in segment.directives.to_dict():
        blockers.append(f"{name.replace('_', '-')} directive belongs to the punctuation segment")
    for boundary in boundaries:
        if segment.spoken_start < boundary.position < segment.spoken_end and boundary_is_active(
            boundary, pause_config
        ):
            blockers.append(f"active pause at spoken position {boundary.position}")
    for semantic_boundary in semantic_boundaries:
        if segment.spoken_start < semantic_boundary.position < segment.spoken_end:
            blockers.append(
                f"{semantic_boundary.kind} semantic boundary at spoken position {semantic_boundary.position}"
            )
    for annotation in annotations:
        if _audio_annotation(annotation) and _annotation_overlaps_segment(annotation, segment):
            blockers.append("audio/media occurrence overlaps the punctuation segment")
        elif (
            not _language_annotation(annotation)
            and _semantic_annotation(annotation)
            and (
                annotation.id in segment.annotation_ids
                or _annotation_overlaps_segment(annotation, segment)
            )
        ):
            tag = str(annotation.attrs.get("tag") or annotation.kind).lower().replace("_", "-")
            blockers.append(f"{tag} annotation belongs to the punctuation segment")
    return tuple(dict.fromkeys(blockers))


def _annotation_overlaps_segment(annotation: AnnotationSpan, segment: PlanSegment) -> bool:
    start, end = annotation.spoken_start, annotation.spoken_end
    if start is None or end is None:
        return False
    if start == end:
        return segment.spoken_start <= start <= segment.spoken_end
    return start < segment.spoken_end and end > segment.spoken_start


def _audio_join_blocker(
    gap_start: int, gap_end: int, annotations: tuple[AnnotationSpan, ...]
) -> str | None:
    for annotation in annotations:
        if not _audio_annotation(annotation):
            continue
        start, end = annotation.spoken_start, annotation.spoken_end
        if start is None or end is None:
            continue
        if start == end and gap_start <= start <= gap_end:
            return f"zero-width audio event at join at spoken position {start}"
        if gap_start == gap_end and start < gap_start < end:
            return "audio/media span crosses the join"
        if start < gap_end and end > gap_start:
            return "audio/media span crosses the join"
    return None


def _audio_annotation(annotation: AnnotationSpan) -> bool:
    tag = str(annotation.attrs.get("tag") or annotation.kind).lower().replace("_", "-")
    return tag == "audio" or annotation.attrs.get("src") is not None


def _language_annotation(annotation: AnnotationSpan) -> bool:
    return set(annotation.attrs).issubset({"lang", "language", "tag"}) and (
        "lang" in annotation.attrs or "language" in annotation.attrs
    )


def _semantic_annotation(annotation: AnnotationSpan) -> bool:
    tag = str(annotation.attrs.get("tag") or annotation.kind).lower().replace("_", "-")
    semantic_tags = {
        "voice",
        "lang",
        "phoneme",
        "pronunciation",
        "prosody",
        "emphasis",
        "say-as",
        "sub",
        "audio",
        "extension",
        "directive",
    }
    if tag in semantic_tags:
        return True
    semantic_attrs = {
        "lang",
        "language",
        "voice",
        "voice-name",
        "voice-languages",
        "gender",
        "age",
        "variant",
        "ph",
        "alphabet",
        "ipa",
        "sampa",
        "rate",
        "pitch",
        "volume",
        "emphasis",
        "as",
        "format",
        "detail",
        "sub",
        "src",
        "desc",
        "clip",
        "speed",
        "repeat",
        "repeatdur",
        "repeatDur",
        "level",
        "ext",
    }
    return any(key in annotation.attrs for key in semantic_attrs)


def _is_neutral_punctuation_text(value: str) -> bool:
    significant = [character for character in value if not character.isspace()]
    return bool(significant) and all(
        unicodedata.category(character).startswith("P") for character in significant
    )


def assert_renderable(plan: UtterancePlan) -> None:
    report = preflight_renderability(plan)
    if report.issues:
        raise PlanValidationError(
            "renderer segment contains no semantic speech content",
            code="segment.not_renderable",
            path=f"$.segments[{report.issues[0].segment_index}]",
        )


def _has_explicit_speech_semantics(segment: PlanSegment) -> bool:
    directives = segment.directives
    if directives.audio is not None:
        return bool(directives.audio.src.strip())
    if directives.substitution is not None:
        return contains_speech_content(directives.substitution.alias)
    if directives.pronunciation is not None:
        return bool(directives.pronunciation.phonemes.strip())
    if directives.say_as is not None:
        kind = directives.say_as.interpret_as.strip().lower().replace("_", "-")
        return kind in {
            "address",
            "cardinal",
            "characters",
            "currency",
            "date",
            "digits",
            "duration",
            "email",
            "expletive",
            "fraction",
            "measure",
            "name",
            "net",
            "number",
            "ordinal",
            "spell-out",
            "telephone",
            "time",
            "unit",
            "url",
            "verbatim",
        }
    return False


def _line_column(text: str, offset: int) -> tuple[int, int]:
    offset = max(0, min(len(text), offset))
    line = text.count("\n", 0, offset) + 1
    previous_newline = text.rfind("\n", 0, offset)
    return line, offset - previous_newline


def _source_excerpt(text: str, offset: int, *, limit: int = 160) -> str:
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    if end < 0:
        end = len(text)
    excerpt = text[start:end].strip("\r")
    if len(excerpt) > limit:
        local_offset = max(0, offset - start)
        left = max(0, min(local_offset - limit // 2, len(excerpt) - limit))
        excerpt = ("…" if left else "") + excerpt[left : left + limit]
        if left + limit < len(text[start:end]):
            excerpt += "…"
    return excerpt


def _source_context(
    text: str, start_offset: int, end_offset: int | None, *, limit: int = 180
) -> tuple[tuple[tuple[int, str], ...], int | None]:
    if not text:
        return (), None
    start_line, start_column = _line_column(text, start_offset)
    end_line = _line_column(text, end_offset)[0] if end_offset is not None else start_line
    lines = text.splitlines()
    first = max(1, start_line - 1)
    last = min(len(lines), max(start_line, end_line) + 1)
    selected: list[tuple[int, str]] = []
    caret: int | None = None
    for number in range(first, last + 1):
        value = lines[number - 1]
        if len(value) > limit:
            if number == start_line:
                position = max(0, start_column - 1)
                left = max(0, min(position - limit // 2, len(value) - limit))
                right = left + limit
                value = ("…" if left else "") + value[left:right]
                if right < len(lines[number - 1]):
                    value += "…"
                caret = position - left + (1 if left else 0)
            else:
                value = value[:limit] + "…"
        elif number == start_line:
            caret = max(0, start_column - 1)
        selected.append((number, value))
    return tuple(selected), caret


def _spoken_context(text: str, start: int, end: int, *, radius: int = 36) -> str:
    start = max(0, min(len(text), start))
    end = max(start, min(len(text), end))
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    value = text[left:start] + "[" + text[start:end] + "]" + text[end:right]
    value = value.replace("\n", " ↵ ").replace("\r", "")
    return ("…" if left else "") + value + ("…" if right < len(text) else "")


def format_renderability_error(
    issues: Sequence[RenderabilityIssue] | PlanRenderabilityError,
    *,
    mode: str | None = None,
    source_label: str | None = None,
    technical: bool = False,
) -> str:
    """Format structured renderability issues for Python, CLI, and batch callers."""
    if isinstance(issues, PlanRenderabilityError):
        selected_issues = issues.issues
        selected_mode = mode or issues.mode
    else:
        selected_issues = tuple(issues)
        selected_mode = mode or "strict"
    source = source_label or "input"
    count = len(selected_issues)
    lines = [
        f"UtterPlan found {count} renderer segment{'s' if count != 1 else ''} without speech intent."
    ]
    for issue in selected_issues:
        if issue.reason == "punctuation_only":
            message = "isolated punctuation became its own speech segment"
            explanation = "Punctuation alone has no speech content."
        elif issue.reason == "symbol_only":
            message = "this symbol has no declared spoken interpretation"
            explanation = "UtterPlan cannot choose a renderer-neutral spoken name for this symbol."
        elif issue.reason == "whitespace_only":
            message = "this renderer segment contains only whitespace"
            explanation = "Whitespace alone does not provide speech content."
        elif issue.reason == "empty":
            message = "this renderer segment is empty"
            explanation = "An empty renderer segment has no speech content."
        else:
            message = "this renderer segment has no semantic speech content"
            explanation = "This renderer segment has no declared speech interpretation."
        location = (
            f"{source}:{issue.line}:{issue.column}: "
            if issue.line is not None and issue.column is not None
            else f"{source}: "
        )
        lines.append(f"\n{location}{message}.")
        if issue.source_context:
            lines.append("  Source context:")
            width = max(len(str(number)) for number, _value in issue.source_context)
            for number, value in issue.source_context:
                lines.append(f"    {number:>{width}} | {value}")
                if number == issue.line and issue.source_caret is not None:
                    lines.append(f"    {' ' * width} | {' ' * issue.source_caret}^")
        elif issue.source_excerpt is not None:
            lines.append(f"  Source: {issue.source_excerpt}")
            if issue.source_caret is not None:
                lines.append(f"          {' ' * issue.source_caret}^")
        lines.append(f"  Prepared fragment: {issue.text!r}")
        lines.append(f"  What happened: {explanation}")
        if issue.spoken_context is not None:
            lines.append(f"  Spoken context: {issue.spoken_context!r}")

        assessment = issue.repair_assessment
        if assessment is not None and assessment.safe:
            action = {
                "merge_previous": "merge with the previous spoken segment",
                "merge_next": "merge with the following spoken segment",
                "drop": "remove the isolated punctuation-only segment",
                "none": "no automatic repair",
            }[assessment.action]
            lines.append(f"  Automatic repair: safe; {action}.")
            if assessment.blockers:
                lines.append("  Other blocked action(s): " + "; ".join(assessment.blockers))
            if selected_mode == "strict":
                lines.append(
                    "  Action: use the default repair mode, or omit --renderability strict."
                )
        else:
            lines.append("  Automatic repair: unavailable; no speech is guessed.")
            if assessment is not None and assessment.blockers:
                lines.append("  Blockers: " + "; ".join(assessment.blockers))
            if issue.hint:
                lines.append(f"  Action: {issue.hint}")
        if technical:
            lines.append("  Details:")
            lines.append(f"    code: {issue.code}")
            lines.append(f"    segment: {issue.segment_id} (index {issue.segment_index})")
            lines.append(f"    spoken range: {issue.spoken_start}:{issue.spoken_end}")
            if issue.structural_start is not None and issue.structural_end is not None:
                lines.append(
                    f"    structural range: {issue.structural_start}:{issue.structural_end}"
                )
            if issue.source_start is not None and issue.source_end is not None:
                lines.append(f"    source range: {issue.source_start}:{issue.source_end}")
    return "\n".join(lines)


__all__ = [
    "RenderabilityAction",
    "RenderabilityIssue",
    "RenderabilityMode",
    "RenderabilityRepair",
    "RenderabilityReport",
    "assess_renderability_repair",
    "assert_renderable",
    "classify_segment",
    "contains_speech_content",
    "format_renderability_error",
    "preflight_renderability",
]
