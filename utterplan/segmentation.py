from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Literal

from .exceptions import PlanValidationError
from .language import language_lookup_key
from .renderability import contains_speech_content
from .token_topology import find_boundary_conflict

BoundaryLevel = Literal["sentence", "part"]


@dataclass(frozen=True, slots=True)
class BoundaryCandidate:
    position: int
    level: BoundaryLevel
    origin: str
    reason: str
    confidence: int
    language_run_id: str | None = None


@dataclass(frozen=True, slots=True)
class ParagraphRegion:
    start: int
    end: int
    paragraph_index: int


@dataclass(frozen=True, slots=True)
class SentenceSpan:
    start: int
    end: int
    paragraph_index: int
    sentence_index: int


@dataclass(frozen=True, slots=True)
class SentencePart:
    start: int
    end: int
    paragraph_index: int
    sentence_index: int
    part_index: int
    boundary_after: str | None = None
    boundary_origin: str | None = None


@dataclass(frozen=True, slots=True)
class SegmentationRepair:
    code: str
    message: str
    spoken_start: int | None = None
    spoken_end: int | None = None
    original_position: int | None = None
    repaired_position: int | None = None
    origin: str | None = None


@dataclass(frozen=True, slots=True)
class SentenceTopology:
    sentences: tuple[SentenceSpan, ...]
    parts: tuple[SentencePart, ...]
    repairs: tuple[SegmentationRepair, ...]
    degraded: bool = False


@dataclass(frozen=True, slots=True)
class SentenceProposalBatch:
    candidates: tuple[BoundaryCandidate, ...]
    repairs: tuple[SegmentationRepair, ...]
    degraded: bool


def propose_phrasplit_sentence_boundaries(
    text: str,
    *,
    language: str,
    run_start: int,
    run_id: str,
) -> SentenceProposalBatch:
    """Adapt PhraseSplit sentence spans into validated UtterPlan boundary proposals.

    PhraseSplit spans are untrusted proposals, not canonical topology. Whitespace
    may be omitted between spans or at the edges, but any omitted non-whitespace
    content invalidates the entire batch. Run endpoints are intentionally not
    emitted as sentence evidence: language-run boundaries can occur mid-sentence.
    """
    try:
        phrasplit = import_module("phrasplit")
    except ImportError:
        return _degraded_batch(
            "segmentation.phrasplit_unavailable",
            f"PhraseSplit is unavailable for spoken range {run_start}:{run_start + len(text)}; "
            "sentence fallback is required",
            run_start,
            run_start + len(text),
        )

    try:
        raw = phrasplit.split_with_offsets(
            text,
            mode="sentence",
            use_spacy=False,
            language=language_lookup_key(language),
        )
        items = list(raw)
    except Exception as exc:
        return _degraded_batch(
            "segmentation.phrasplit_failed",
            f"PhraseSplit failed for spoken range {run_start}:{run_start + len(text)} "
            f"({type(exc).__name__}); sentence fallback is required",
            run_start,
            run_start + len(text),
        )

    validated: list[tuple[int, int, str]] = []
    previous_end = 0
    invalid_reason: str | None = None
    for index, item in enumerate(items):
        try:
            start = getattr(item, "char_start", None)
            end = getattr(item, "char_end", None)
            surface = getattr(item, "text", None)
        except Exception:
            invalid_reason = f"proposal {index} could not be read"
            break

        if type(start) is not int or type(end) is not int:
            invalid_reason = f"proposal {index} has non-integer offsets"
            break
        if not isinstance(surface, str):
            invalid_reason = f"proposal {index} has no text surface"
            break
        if not 0 <= start < end <= len(text):
            invalid_reason = f"proposal {index} has out-of-range or empty offsets"
            break
        if start < previous_end:
            invalid_reason = f"proposal {index} overlaps or is out of order"
            break
        if surface != text[start:end]:
            invalid_reason = f"proposal {index} surface does not match its offsets"
            break
        if text[previous_end:start].strip():
            invalid_reason = f"uncovered non-whitespace text at {previous_end}:{start}"
            break
        validated.append((start, end, surface))
        previous_end = end

    if invalid_reason is None and text[previous_end:].strip():
        invalid_reason = f"uncovered non-whitespace text at {previous_end}:{len(text)}"

    if invalid_reason is not None:
        return _degraded_batch(
            "segmentation.phrasplit_invalid",
            f"Discarded the PhraseSplit proposal batch for spoken range "
            f"{run_start}:{run_start + len(text)}: {invalid_reason}; "
            "sentence fallback is required",
            run_start,
            run_start + len(text),
        )

    candidates = tuple(
        BoundaryCandidate(
            position=run_start + end,
            level="sentence",
            origin="phrasplit",
            reason="PhraseSplit sentence boundary before another proposal in this language run",
            confidence=80,
            language_run_id=run_id,
        )
        for _start, end, _surface in validated[:-1]
    )
    return SentenceProposalBatch(candidates=candidates, repairs=(), degraded=False)


def build_paragraph_regions(
    spoken: str,
    boundaries: Sequence[Any],
) -> tuple[ParagraphRegion, ...]:
    """Build paragraph containers from parser-provided paragraph events."""
    positions = {0, len(spoken)}
    for boundary in boundaries:
        position = getattr(boundary, "position", None)
        if (
            getattr(boundary, "kind", None) == "paragraph"
            and type(position) is int
            and 0 < position < len(spoken)
        ):
            positions.add(position)

    regions: list[ParagraphRegion] = []
    ordered = sorted(positions)
    for start, end in zip(ordered, ordered[1:], strict=False):
        while start < end and spoken[start].isspace():
            start += 1
        while end > start and spoken[end - 1].isspace():
            end -= 1
        if start >= end:
            continue
        regions.append(ParagraphRegion(start, end, len(regions)))
    return tuple(regions)


def fallback_terminal_candidates(
    spoken: str,
    paragraphs: Sequence[ParagraphRegion],
    *,
    origin: str = "terminal-punctuation",
) -> tuple[BoundaryCandidate, ...]:
    """Find conservative high-confidence sentence boundaries in paragraph spans."""
    candidates: list[BoundaryCandidate] = []
    for paragraph in paragraphs:
        text = spoken
        position = paragraph.start
        while position < paragraph.end:
            char = text[position]
            if char not in ".!?。｡！？」؟﹖﹗…":
                position += 1
                continue

            terminal_start = position
            if char == ".":
                while terminal_start > paragraph.start and text[terminal_start - 1] == ".":
                    terminal_start -= 1
                terminal_end = position + 1
                while terminal_end < paragraph.end and text[terminal_end] == ".":
                    terminal_end += 1
                dot_count = terminal_end - terminal_start
                if position != terminal_end - 1:
                    position += 1
                    continue
                if dot_count == 1 and _protected_period(text, position, paragraph.start):
                    position += 1
                    continue
                is_ellipsis = dot_count > 1
            else:
                terminal_end = position + 1
                while terminal_end < paragraph.end and text[terminal_end] in "!?。｡！？」؟﹖﹗":
                    terminal_end += 1
                is_ellipsis = char == "…"
                if is_ellipsis:
                    while terminal_end < paragraph.end and text[terminal_end] == "…":
                        terminal_end += 1

            boundary_end = terminal_end
            has_closing = False
            while boundary_end < paragraph.end and _is_closing_punctuation(text[boundary_end]):
                has_closing = True
                boundary_end += 1
            whitespace_end = boundary_end
            while whitespace_end < paragraph.end and text[whitespace_end].isspace():
                whitespace_end += 1
            if whitespace_end >= paragraph.end:
                position = max(position + 1, boundary_end)
                continue
            following = text[whitespace_end : paragraph.end]
            if not contains_speech_content(following):
                position += 1
                continue

            next_speech = next((character for character in following if character.isalnum()), "")
            strong_terminal = char in "!?。｡！？」؟﹖﹗"
            quote_terminal = has_closing
            if is_ellipsis or char == ".":
                strong_terminal = bool(next_speech and next_speech.isupper())
            if strong_terminal or quote_terminal:
                candidates.append(
                    BoundaryCandidate(
                        position=boundary_end,
                        level="sentence",
                        origin=origin,
                        reason="conservative terminal punctuation fallback",
                        confidence=70 if quote_terminal else 55,
                    )
                )
            position = max(position + 1, terminal_end)
    return tuple(candidates)


def normalize_sentence_candidates(
    spoken: str,
    paragraphs: Sequence[ParagraphRegion],
    candidates: Sequence[BoundaryCandidate],
    *,
    tokens: Sequence[Any],
    token_providers: Sequence[str | None],
    protected_spans: Sequence[tuple[int, int]] = (),
) -> tuple[tuple[SentenceSpan, ...], tuple[SegmentationRepair, ...]]:
    """Normalize automatic sentence boundaries and assign compiler-owned indices."""
    ordered_candidates = sorted(
        candidates,
        key=lambda item: (item.position, -item.confidence, item.origin, item.reason),
    )
    sentences: list[SentenceSpan] = []
    dropped_lexical = 0
    dropped_speechless = 0
    dropped_atomic = 0
    for paragraph in paragraphs:
        local = [
            item for item in ordered_candidates if paragraph.start < item.position < paragraph.end
        ]
        unique: list[BoundaryCandidate] = []
        seen_positions: set[int] = set()
        for candidate in local:
            if _inside_protected_span(candidate.position, protected_spans):
                dropped_atomic += 1
                continue
            position = _attach_closing_cluster(spoken, candidate.position, paragraph.end)
            if _inside_protected_span(position, protected_spans):
                dropped_atomic += 1
                continue
            if not paragraph.start < position < paragraph.end or position in seen_positions:
                continue
            seen_positions.add(position)
            conflict = find_boundary_conflict(
                position,
                tokens=tokens,
                token_providers=token_providers,
            )
            if conflict is not None:
                dropped_lexical += 1
                continue
            unique.append(
                BoundaryCandidate(
                    position=position,
                    level="sentence",
                    origin=candidate.origin,
                    reason=candidate.reason,
                    confidence=candidate.confidence,
                    language_run_id=candidate.language_run_id,
                )
            )

        cursor = paragraph.start
        sentence_index = 0
        for candidate in unique:
            boundary = candidate.position
            if not contains_speech_content(spoken[cursor:boundary]) or not contains_speech_content(
                spoken[boundary : paragraph.end]
            ):
                dropped_speechless += 1
                continue
            span_start, span_end = _trim_whitespace(spoken, cursor, boundary)
            if contains_speech_content(spoken[span_start:span_end]):
                sentences.append(
                    SentenceSpan(span_start, span_end, paragraph.paragraph_index, sentence_index)
                )
                sentence_index += 1
            cursor = boundary

        span_start, span_end = _trim_whitespace(spoken, cursor, paragraph.end)
        if contains_speech_content(spoken[span_start:span_end]):
            sentences.append(
                SentenceSpan(span_start, span_end, paragraph.paragraph_index, sentence_index)
            )

    repairs: list[SegmentationRepair] = []
    if dropped_lexical:
        repairs.append(
            SegmentationRepair(
                code="segmentation.lexical_boundary_merged",
                message=f"Dropped {dropped_lexical} automatic sentence boundary candidate(s) "
                "that split lexical content; merged the surrounding sentence spans",
                origin="automatic",
            )
        )
    if dropped_speechless:
        repairs.append(
            SegmentationRepair(
                code="segmentation.sentence_candidate_dropped",
                message=f"Dropped {dropped_speechless} sentence boundary candidate(s) "
                "that would create a speechless sentence",
                origin="automatic",
            )
        )
    if dropped_atomic:
        repairs.append(
            SegmentationRepair(
                "segmentation.atomic_boundary_dropped",
                f"Dropped {dropped_atomic} sentence boundary candidate(s) inside "
                "positive-width atomic audio spans",
                origin="automatic",
            )
        )
    return tuple(sentences), tuple(repairs)


def detect_part_candidates(
    spoken: str,
    sentence: SentenceSpan,
    optional_boundaries: Sequence[Any] = (),
) -> tuple[BoundaryCandidate, ...]:
    """Collect deterministic punctuation and optional trusted clause proposals."""
    candidates: list[BoundaryCandidate] = []
    position = sentence.start
    while position < sentence.end:
        char = spoken[position]
        if char in ";；" and not _inside_url_like_token(spoken, position):
            boundary = _separator_boundary_end(spoken, position + 1, sentence.end)
            if contains_speech_content(
                spoken[sentence.start : position]
            ) and contains_speech_content(spoken[boundary : sentence.end]):
                candidates.append(
                    BoundaryCandidate(
                        boundary,
                        "part",
                        "semicolon",
                        "semicolon sentence-part separator",
                        90,
                    )
                )
            position += 1
            continue
        if char in ":：":
            if char == ":" and _ascii_colon_has_prose_context(spoken, position, sentence.end):
                boundary = _separator_boundary_end(spoken, position + 1, sentence.end)
                if contains_speech_content(
                    spoken[sentence.start : position]
                ) and contains_speech_content(spoken[boundary : sentence.end]):
                    candidates.append(
                        BoundaryCandidate(
                            boundary,
                            "part",
                            "colon",
                            "contextual colon sentence-part separator",
                            75,
                        )
                    )
            elif char == "：" and not _fullwidth_colon_is_numeric(spoken, position):
                boundary = _separator_boundary_end(spoken, position + 1, sentence.end)
                if contains_speech_content(
                    spoken[sentence.start : position]
                ) and contains_speech_content(spoken[boundary : sentence.end]):
                    candidates.append(
                        BoundaryCandidate(
                            boundary,
                            "part",
                            "colon",
                            "fullwidth colon sentence-part separator",
                            70,
                        )
                    )
        position += 1

    for boundary in optional_boundaries:
        kind = getattr(boundary, "kind", None)
        candidate_position = getattr(boundary, "position", None)
        if kind not in {"clause", "parenthetical"} or type(candidate_position) is not int:
            continue
        if not sentence.start < candidate_position < sentence.end:
            continue
        candidates.append(
            BoundaryCandidate(
                candidate_position,
                "part",
                "phrasplit-clause" if kind == "clause" else "parenthetical",
                "optional PhraseSplit clause or parenthetical proposal",
                45,
                getattr(boundary, "language_run_id", None),
            )
        )
    return tuple(candidates)


def normalize_sentence_parts(
    spoken: str,
    sentence: SentenceSpan,
    candidates: Sequence[BoundaryCandidate],
    *,
    tokens: Sequence[Any],
    token_providers: Sequence[str | None],
    protected_spans: Sequence[tuple[int, int]] = (),
) -> tuple[tuple[SentencePart, ...], tuple[SegmentationRepair, ...]]:
    """Normalize part boundaries, keeping separators and horizontal space on the left."""
    ordered = sorted(
        (candidate for candidate in candidates if candidate.level == "part"),
        key=lambda item: (item.position, -item.confidence, item.origin),
    )
    unique: list[BoundaryCandidate] = []
    seen: set[int] = set()
    dropped_atomic = 0
    for candidate in ordered:
        position = candidate.position
        if _inside_protected_span(position, protected_spans):
            dropped_atomic += 1
            continue
        if not sentence.start < position < sentence.end or position in seen:
            continue
        seen.add(position)
        unique.append(
            BoundaryCandidate(
                position,
                "part",
                candidate.origin,
                candidate.reason,
                candidate.confidence,
                candidate.language_run_id,
            )
        )

    # Collapse runs of separators with no speech between them to their rightmost
    # edge, so e.g. "Hello; ; world" never creates a punctuation-only part.
    clustered: list[BoundaryCandidate] = []
    index = 0
    while index < len(unique):
        cluster_end = index
        while cluster_end + 1 < len(unique) and not contains_speech_content(
            spoken[unique[cluster_end].position : unique[cluster_end + 1].position]
        ):
            cluster_end += 1
        clustered.append(unique[cluster_end])
        index = cluster_end + 1

    accepted: list[BoundaryCandidate] = []
    dropped_lexical = 0
    dropped_speechless = max(0, len(unique) - len(clustered))
    cursor = sentence.start
    for candidate in clustered:
        position = candidate.position
        if not contains_speech_content(spoken[cursor:position]) or not contains_speech_content(
            spoken[position : sentence.end]
        ):
            dropped_speechless += 1
            continue
        if (
            find_boundary_conflict(
                position,
                tokens=tokens,
                token_providers=token_providers,
            )
            is not None
        ):
            dropped_lexical += 1
            continue
        accepted.append(candidate)
        cursor = position

    parts: list[SentencePart] = []
    cursor = sentence.start
    for part_index, candidate in enumerate(accepted):
        parts.append(
            SentencePart(
                cursor,
                candidate.position,
                sentence.paragraph_index,
                sentence.sentence_index,
                part_index,
                boundary_after=candidate.origin,
                boundary_origin=candidate.origin,
            )
        )
        cursor = candidate.position
    parts.append(
        SentencePart(
            cursor,
            sentence.end,
            sentence.paragraph_index,
            sentence.sentence_index,
            len(parts),
        )
    )

    repairs: list[SegmentationRepair] = []
    if dropped_lexical:
        repairs.append(
            SegmentationRepair(
                "segmentation.part_candidate_dropped",
                f"Dropped {dropped_lexical} automatic sentence-part candidate(s) "
                "that split lexical content; kept a wider part",
                sentence.start,
                sentence.end,
                origin="automatic",
            )
        )
    if dropped_speechless:
        repairs.append(
            SegmentationRepair(
                "segmentation.part_candidate_dropped",
                f"Collapsed {dropped_speechless} sentence-part candidate(s) "
                "that would create a speechless part",
                sentence.start,
                sentence.end,
                origin="automatic",
            )
        )
    if dropped_atomic:
        repairs.append(
            SegmentationRepair(
                "segmentation.atomic_boundary_dropped",
                f"Dropped {dropped_atomic} sentence-part candidate(s) inside "
                "positive-width atomic audio spans",
                sentence.start,
                sentence.end,
                origin="automatic",
            )
        )
    return tuple(parts), tuple(repairs)


def _ascii_colon_has_prose_context(text: str, position: int, limit: int) -> bool:
    if position == 0 or position + 1 >= limit:
        return False
    if text[position - 1] == ":" or text[position + 1] in ":/\\":
        return False
    if text[position - 1].isdigit() and text[position + 1].isdigit():
        return False
    next_position = position + 1
    if _is_horizontal_space(text[next_position]):
        while next_position < limit and _is_horizontal_space(text[next_position]):
            next_position += 1
        return next_position < limit
    return text[next_position] in "\"'“‘«„‹([{「『（【"


def _fullwidth_colon_is_numeric(text: str, position: int) -> bool:
    return (
        position > 0
        and position + 1 < len(text)
        and text[position - 1].isdigit()
        and text[position + 1].isdigit()
    )


def _inside_url_like_token(text: str, position: int) -> bool:
    start = position
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    end = position + 1
    while end < len(text) and not text[end].isspace():
        end += 1
    token = text[start:end]
    return "://" in token or token.casefold().startswith(("mailto:", "www."))


def _separator_boundary_end(text: str, position: int, limit: int) -> int:
    position = _attach_closing_cluster(text, position, limit)
    return _consume_horizontal_space(text, position, limit)


def _consume_horizontal_space(text: str, position: int, limit: int) -> int:
    while position < limit and _is_horizontal_space(text[position]):
        position += 1
    return position


def _is_horizontal_space(character: str) -> bool:
    return character == "\t" or unicodedata.category(character) == "Zs"


def _normalize_protected_spans(
    spans: Sequence[tuple[int, int]], text_length: int
) -> tuple[tuple[int, int], ...]:
    ordered = sorted(
        (start, end)
        for start, end in spans
        if type(start) is int and type(end) is int and 0 <= start < end <= text_length
    )
    merged: list[tuple[int, int]] = []
    for start, end in ordered:
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _inside_protected_span(position: int, spans: Sequence[tuple[int, int]]) -> bool:
    index = bisect_right(spans, position, key=lambda span: span[0]) - 1
    return index >= 0 and spans[index][0] < position < spans[index][1]


def build_sentence_topology(
    spoken: str,
    runs: Sequence[Any],
    boundaries: Sequence[Any],
    *,
    tokens: Sequence[Any],
    token_providers: Sequence[str | None],
    optional_part_boundaries: Sequence[Any] = (),
    protected_spans: Sequence[tuple[int, int]] = (),
) -> SentenceTopology:
    """Build compiler-owned paragraph, sentence, and sentence-part topology."""
    paragraphs = build_paragraph_regions(spoken, boundaries)
    protected_spans = _normalize_protected_spans(protected_spans, len(spoken))
    candidates: list[BoundaryCandidate] = []
    repairs: list[SegmentationRepair] = []
    degraded = False
    for run in runs:
        batch = propose_phrasplit_sentence_boundaries(
            spoken[run.spoken_start : run.spoken_end],
            language=run.language,
            run_start=run.spoken_start,
            run_id=run.id,
        )
        candidates.extend(batch.candidates)
        repairs.extend(batch.repairs)
        degraded = degraded or batch.degraded

    candidates.extend(fallback_terminal_candidates(spoken, paragraphs))
    sentences, repairs_from_normalization = normalize_sentence_candidates(
        spoken,
        paragraphs,
        candidates,
        tokens=tokens,
        token_providers=token_providers,
        protected_spans=protected_spans,
    )
    repairs.extend(repairs_from_normalization)

    parts: list[SentencePart] = []
    for sentence in sentences:
        part_candidates = detect_part_candidates(
            spoken,
            sentence,
            optional_boundaries=optional_part_boundaries,
        )
        sentence_parts, part_repairs = normalize_sentence_parts(
            spoken,
            sentence,
            part_candidates,
            tokens=tokens,
            token_providers=token_providers,
            protected_spans=protected_spans,
        )
        parts.extend(sentence_parts)
        repairs.extend(part_repairs)
    return SentenceTopology(tuple(sentences), tuple(parts), tuple(repairs), degraded)


def validate_non_whitespace_coverage(spoken: str, segments: Sequence[Any]) -> None:
    """Validate exact, ordered segment surfaces and complete non-whitespace coverage."""
    previous_end = 0
    for segment in sorted(segments, key=lambda item: (item.spoken_start, item.spoken_end)):
        start, end = segment.spoken_start, segment.spoken_end
        if not 0 <= start <= end <= len(spoken):
            raise PlanValidationError(
                f"segment {segment.id} has invalid spoken span [{start}:{end}]",
                code="segmentation.segment_span",
            )
        if start == end:
            if segment.text != spoken[start:end]:
                raise PlanValidationError(
                    f"zero-width segment {segment.id} has a non-empty surface",
                    code="segmentation.segment_surface",
                )
            continue
        if start < previous_end:
            raise PlanValidationError(
                f"segment {segment.id} overlaps the preceding renderer segment",
                code="segmentation.segment_overlap",
            )
        if segment.text != spoken[start:end]:
            raise PlanValidationError(
                f"segment {segment.id} surface differs from spoken text [{start}:{end}]",
                code="segmentation.segment_surface",
            )
        gap = spoken[previous_end:start]
        if gap.strip():
            raise PlanValidationError(
                f"non-whitespace spoken content is uncovered at [{previous_end}:{start}]",
                code="segmentation.content_gap",
            )
        previous_end = end
    tail = spoken[previous_end:]
    if tail.strip():
        raise PlanValidationError(
            f"non-whitespace spoken content is uncovered at [{previous_end}:{len(spoken)}]",
            code="segmentation.content_gap",
        )


def _degraded_batch(
    code: str,
    message: str,
    spoken_start: int,
    spoken_end: int,
) -> SentenceProposalBatch:
    return SentenceProposalBatch(
        candidates=(),
        repairs=(
            SegmentationRepair(
                code=code,
                message=message,
                spoken_start=spoken_start,
                spoken_end=spoken_end,
                origin="phrasplit",
            ),
        ),
        degraded=True,
    )


def _protected_period(text: str, position: int, paragraph_start: int) -> bool:
    left = text[paragraph_start:position]
    token_match = re.search(r"[^\s]+$", left)
    token = token_match.group(0) if token_match else ""
    folded = token.casefold().rstrip(".,;:!?\"'”’)]}")
    if folded in {
        "dr",
        "mr",
        "mrs",
        "ms",
        "prof",
        "sr",
        "jr",
        "st",
        "vs",
        "etc",
        "eg",
        "e.g",
        "ie",
        "i.e",
        "no",
        "fig",
        "inc",
        "dept",
    }:
        return True
    if re.fullmatch(r"(?:\w\.)+\w?", token, flags=re.UNICODE):
        return True
    previous = token.rstrip(".")
    return len(previous) == 1 and previous.isalpha()


def _attach_closing_cluster(text: str, position: int, limit: int) -> int:
    while position < limit and _is_closing_punctuation(text[position]):
        position += 1
    return position


def _is_closing_punctuation(character: str) -> bool:
    return character in "\"'»”’)]}】》」』〕〉）］｝〗〙〛"


def _trim_whitespace(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end
