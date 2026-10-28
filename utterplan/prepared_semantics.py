from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from .model import AnnotationSpan
from .preparation import PreparedText

_SOURCE_SPELLING = re.compile(r"(?P<core>[A-Z0-9]{2,})(?P<suffix>'s|’s)?\Z")
_DERIVED_ORIGIN = "derived-character-spelling"


@dataclass(frozen=True, slots=True)
class CharacterSpellingMatch:
    """Core offsets inside a source/replacement pair that spell characters exactly."""

    source_core_start: int
    source_core_end: int
    output_core_start: int
    output_core_end: int


def detect_character_spelling(source: str, replacement: str) -> CharacterSpellingMatch | None:
    """Match only exact, conservative uppercase-letter/digit character spellings."""
    if not isinstance(source, str) or not isinstance(replacement, str):
        return None
    source_match = _SOURCE_SPELLING.fullmatch(source)
    if source_match is None:
        return None

    source_core = source_match.group("core")
    suffix = source_match.group("suffix") or ""
    replacement_core = " ".join(source_core)
    if replacement != replacement_core + suffix:
        return None

    return CharacterSpellingMatch(
        source_core_start=0,
        source_core_end=len(source_core),
        output_core_start=0,
        output_core_end=len(replacement_core),
    )


def infer_prepared_semantics(prepared: PreparedText) -> PreparedText:
    """Add deterministic say-as annotations implied by verified replacements.

    Prepared text, preparation provenance, boundaries, source mapping, and consumed
    substitutions remain untouched. Only the immutable annotation tuple is extended.
    """
    existing_ids = {annotation.id for annotation in prepared.annotations}
    existing_say_as = tuple(
        span
        for annotation in prepared.annotations
        if _is_say_as(annotation)
        if (span := _spoken_span(annotation, prepared)) is not None
    )
    additions: list[AnnotationSpan] = []
    occupied = list(existing_say_as)

    verified_replacements = [
        (verified, raw)
        for raw in prepared.info.replacements
        if (verified := _verified_replacement(raw, prepared)) is not None
    ]
    verified_replacements.sort(
        key=lambda item: (
            *item[0][:4],
            item[0][4],
            item[0][5],
            str(item[1].get("annotation_id", "")),
        )
    )
    for verified, raw in verified_replacements:
        source_start, source_end, output_start, output_end, source, replacement = verified
        match = detect_character_spelling(source, replacement)
        if match is None:
            continue

        structural_start = source_start + match.source_core_start
        structural_end = source_start + match.source_core_end
        spoken_start = output_start + match.output_core_start
        spoken_end = output_start + match.output_core_end
        if any(_overlaps((spoken_start, spoken_end), span) for span in occupied):
            continue

        annotation_id = (
            "derived.say-as.characters."
            f"{structural_start}.{structural_end}.{spoken_start}.{spoken_end}"
        )
        if annotation_id in existing_ids:
            continue

        origin = _replacement_annotation(raw, prepared.annotations)
        annotation = AnnotationSpan(
            id=annotation_id,
            kind="directive",
            attrs={
                "tag": "say-as",
                "as": "characters",
                "origin": _DERIVED_ORIGIN,
            },
            structural_start=structural_start,
            structural_end=structural_end,
            spoken_start=spoken_start,
            spoken_end=spoken_end,
            source_start=origin.source_start if origin is not None else None,
            source_end=origin.source_end if origin is not None else None,
            source_node_id=origin.source_node_id if origin is not None else None,
        )
        additions.append(annotation)
        existing_ids.add(annotation_id)
        occupied.append((spoken_start, spoken_end))

    if not additions:
        return prepared
    additions.sort(
        key=lambda annotation: (
            annotation.spoken_start if annotation.spoken_start is not None else -1,
            annotation.spoken_end if annotation.spoken_end is not None else -1,
            annotation.id,
        )
    )
    return replace(prepared, annotations=(*prepared.annotations, *additions))


def _verified_replacement(
    raw: Mapping[str, Any], prepared: PreparedText
) -> tuple[int, int, int, int, str, str] | None:
    source_start = raw.get("source_start")
    source_end = raw.get("source_end")
    output_start = raw.get("output_start")
    output_end = raw.get("output_end")
    source = raw.get("source")
    replacement = raw.get("replacement")
    if (
        type(source_start) is not int
        or type(source_end) is not int
        or type(output_start) is not int
        or type(output_end) is not int
        or not isinstance(source, str)
        or not isinstance(replacement, str)
        or not 0 <= source_start < source_end <= prepared.source_map.source_length
        or not 0 <= output_start < output_end <= len(prepared.spoken_text)
        or output_end - output_start != len(replacement)
        or prepared.spoken_text[output_start:output_end] != replacement
    ):
        return None
    try:
        mapped_span = prepared.source_map.map_source_span(source_start, source_end)
        reverse_span = prepared.source_map.map_output_span(output_start, output_end)
    except (TypeError, ValueError):
        return None
    if mapped_span != (output_start, output_end) or reverse_span != (source_start, source_end):
        return None
    return source_start, source_end, output_start, output_end, source, replacement


def _is_say_as(annotation: AnnotationSpan) -> bool:
    attrs = annotation.attrs
    tag = str(attrs.get("tag") or annotation.kind).lower().replace("_", "-")
    return tag == "say-as" or "as" in attrs or "say-as" in attrs


def _spoken_span(annotation: AnnotationSpan, prepared: PreparedText) -> tuple[int, int] | None:
    start, end = annotation.spoken_start, annotation.spoken_end
    if type(start) is int and type(end) is int and 0 <= start < end <= len(prepared.spoken_text):
        return start, end
    try:
        mapped = prepared.source_map.map_source_span(
            annotation.structural_start, annotation.structural_end
        )
    except (TypeError, ValueError):
        return None
    if (
        type(mapped[0]) is int
        and type(mapped[1]) is int
        and 0 <= mapped[0] < mapped[1] <= len(prepared.spoken_text)
    ):
        return mapped
    return None


def _overlaps(candidate: tuple[int, int], existing: tuple[int, int]) -> bool:
    return candidate[0] < existing[1] and existing[0] < candidate[1]


def _replacement_annotation(
    raw: Mapping[str, Any], annotations: tuple[AnnotationSpan, ...]
) -> AnnotationSpan | None:
    annotation_id = raw.get("annotation_id")
    if not isinstance(annotation_id, str):
        return None
    return next((item for item in annotations if item.id == annotation_id), None)
