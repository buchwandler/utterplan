from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from utterplan.model import AnnotationSpan, BoundaryEvent, TextPreparationInfo
from utterplan.preparation import PreparedText
from utterplan.prepared_semantics import (
    CharacterSpellingMatch,
    detect_character_spelling,
    infer_prepared_semantics,
)


@dataclass(frozen=True)
class _MappedSource:
    source_length: int
    output_length: int
    source_start: int
    source_end: int
    output_start: int
    output_end: int

    def map_source_span(self, start: int, end: int) -> tuple[int, int]:
        if (start, end) == (self.source_start, self.source_end):
            return self.output_start, self.output_end
        return start, end

    def map_output_span(self, start: int, end: int) -> tuple[int, int]:
        if (start, end) == (self.output_start, self.output_end):
            return self.source_start, self.source_end
        return start, end


def _replacement(source: str, replacement: str, *, start: int = 0) -> PreparedText:
    output_start = start + 10
    source_map = _MappedSource(
        source_length=start + len(source) + 5,
        output_length=output_start + len(replacement) + 5,
        source_start=start,
        source_end=start + len(source),
        output_start=output_start,
        output_end=output_start + len(replacement),
    )
    spoken = " " * output_start + replacement + " " * 5
    record: dict[str, Any] = {
        "source_start": start,
        "source_end": start + len(source),
        "output_start": output_start,
        "output_end": output_start + len(replacement),
        "source": source,
        "replacement": replacement,
        "kind": "ssmd-sub",
        "rule": "ssmd.sub",
        "annotation_id": "sub-1",
    }
    source_annotation = AnnotationSpan(
        id="sub-1",
        kind="directive",
        attrs={"sub": replacement},
        structural_start=start,
        structural_end=start + len(source),
        spoken_start=output_start,
        spoken_end=output_start + len(replacement),
        source_start=100 + start,
        source_end=100 + start + len(source),
        source_node_id="source-node-1",
    )
    return PreparedText(
        spoken_text=spoken,
        info=TextPreparationInfo("ssmd", None, replacements=(record,)),
        annotations=(source_annotation,),
        boundaries=(BoundaryEvent("b-1", 0, "sentence"),),
        source_map=source_map,
        consumed_substitutions=("sub-1",),
    )


@pytest.mark.parametrize(
    ("source", "replacement", "expected"),
    [
        ("ART", "A R T", CharacterSpellingMatch(0, 3, 0, 5)),
        ("AI", "A I", CharacterSpellingMatch(0, 2, 0, 3)),
        ("USA", "U S A", CharacterSpellingMatch(0, 3, 0, 5)),
        ("R2D2", "R 2 D 2", CharacterSpellingMatch(0, 4, 0, 7)),
        ("ART's", "A R T's", CharacterSpellingMatch(0, 3, 0, 5)),
        ("ART’s", "A R T’s", CharacterSpellingMatch(0, 3, 0, 5)),
    ],
)
def test_detect_exact_character_spelling(
    source: str, replacement: str, expected: CharacterSpellingMatch
) -> None:
    assert detect_character_spelling(source, replacement) == expected


@pytest.mark.parametrize(
    ("source", "replacement"),
    [
        ("A", "A"),
        ("NASA", "nasa"),
        ("NASA", "N A S A agency"),
        ("Dr.", "Doctor"),
        ("kg", "kilograms"),
        ("ART", "A-R-T"),
        ("ABC", "A B C D"),
        ("AB", "A  B"),
        ("A&B", "A and B"),
        ("ARTs", "A R T s"),
        ("ART's", "A R T’s"),
    ],
)
def test_rejects_non_exact_character_spelling(source: str, replacement: str) -> None:
    assert detect_character_spelling(source, replacement) is None


def test_inference_adds_immutable_core_only_deterministic_annotation() -> None:
    prepared = _replacement("ART's", "A R T's", start=4)
    result = infer_prepared_semantics(prepared)
    derived = result.annotations[-1]

    assert result.spoken_text == prepared.spoken_text
    assert result.info is prepared.info
    assert result.info.replacements == prepared.info.replacements
    assert result.boundaries is prepared.boundaries
    assert result.source_map is prepared.source_map
    assert result.consumed_substitutions is prepared.consumed_substitutions
    assert derived.id == "derived.say-as.characters.4.7.14.19"
    assert derived.kind == "directive"
    assert derived.attrs == {
        "tag": "say-as",
        "as": "characters",
        "origin": "derived-character-spelling",
    }
    assert (derived.structural_start, derived.structural_end) == (4, 7)
    assert (derived.spoken_start, derived.spoken_end) == (14, 19)
    assert prepared.spoken_text[derived.spoken_start : derived.spoken_end] == "A R T"
    assert (derived.source_start, derived.source_end) == (104, 109)
    assert derived.source_node_id == "source-node-1"
    assert infer_prepared_semantics(result).annotations == result.annotations


def test_authored_say_as_prevents_derived_overlap_and_wins() -> None:
    prepared = _replacement("ART", "A R T")
    authored = AnnotationSpan(
        id="authored-say-as",
        kind="directive",
        attrs={"tag": "say-as", "as": "initialism"},
        structural_start=0,
        structural_end=3,
        spoken_start=10,
        spoken_end=15,
    )
    prepared = PreparedText(
        prepared.spoken_text,
        prepared.info,
        (*prepared.annotations, authored),
        prepared.boundaries,
        prepared.source_map,
        prepared.consumed_substitutions,
    )

    result = infer_prepared_semantics(prepared)

    assert result is prepared
    assert [item.id for item in result.annotations].count("authored-say-as") == 1
    assert all(
        item.attrs.get("origin") != "derived-character-spelling" for item in result.annotations
    )


def test_unverified_replacement_is_ignored() -> None:
    prepared = _replacement("ART", "A R T")
    bad = dict(
        prepared.info.replacements[0], output_end=prepared.info.replacements[0]["output_end"] - 1
    )
    info = TextPreparationInfo("ssmd", None, replacements=(bad,))
    unverified = PreparedText(
        prepared.spoken_text,
        info,
        prepared.annotations,
        prepared.boundaries,
        prepared.source_map,
        prepared.consumed_substitutions,
    )

    assert infer_prepared_semantics(unverified) is unverified
