from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Literal

from .exceptions import PlanValidationError
from .model import PlanSegment, TokenAnnotation, UtterancePlan
from .parsers import ParsedDocument, map_structural_span_to_source

RenderabilityMode = Literal["strict", "repair"]


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
    token_pos: tuple[str, ...] = ()
    token_ids: tuple[str, ...] = ()
    repair: str | None = None
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
        hint = "Replace the symbol with explicit words or add a supported semantic speech directive; Utterplan will not guess its name."
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
    if isinstance(source_text, str) and source_start is not None:
        line, column = _line_column(source_text, source_start)
        if source_end is not None:
            end_line, end_column = _line_column(source_text, source_end)
        excerpt = _source_excerpt(source_text, source_start)

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
) -> RenderabilityReport:
    issues = tuple(
        issue
        for index, segment in enumerate(segments)
        if (issue := classify_segment(segment, index, tokens, parsed=parsed)) is not None
    )
    return RenderabilityReport(checked_segments=len(segments), issues=issues)


def preflight_renderability(plan: UtterancePlan) -> RenderabilityReport:
    """Inspect every renderer-facing segment in a completed plan."""
    return preflight_segments(plan.segments, plan.tokens)


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


__all__ = [
    "RenderabilityIssue",
    "RenderabilityMode",
    "RenderabilityReport",
    "assert_renderable",
    "classify_segment",
    "contains_speech_content",
    "preflight_renderability",
]
