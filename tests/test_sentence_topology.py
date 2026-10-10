from __future__ import annotations

import random
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from utterplan.model import BoundaryEvent, TokenAnnotation
from utterplan.renderability import contains_speech_content
from utterplan.segmentation import (
    build_paragraph_regions,
    build_sentence_topology,
    validate_non_whitespace_coverage,
)


def _fake_phrasplit(
    monkeypatch: pytest.MonkeyPatch,
    results: list[Any] | None = None,
    *,
    error: Exception | None = None,
) -> None:
    calls = 0

    def split_with_offsets(text: str, **_kwargs: Any) -> list[Any]:
        nonlocal calls
        calls += 1
        if error is not None:
            raise error
        if results is not None:
            return results
        return [
            SimpleNamespace(
                char_start=0, char_end=len(text), text=text, paragraph_idx=42, sentence_idx=99
            )
        ]

    monkeypatch.setitem(
        sys.modules,
        "phrasplit",
        SimpleNamespace(split_with_offsets=split_with_offsets),
    )


def _run(start: int, end: int, run_id: str = "run-1", language: str = "en") -> SimpleNamespace:
    return SimpleNamespace(spoken_start=start, spoken_end=end, id=run_id, language=language)


def test_paragraph_regions_use_parser_events_and_keep_global_order() -> None:
    text = "First.\n\nSecond.\n\nThird."
    events = (
        BoundaryEvent("b1", 6, "paragraph"),
        BoundaryEvent("ignored", 14, "pause"),
        BoundaryEvent("b2", 15, "paragraph"),
    )

    regions = build_paragraph_regions(text, events)

    assert [(item.start, item.end, item.paragraph_index) for item in regions] == [
        (0, 6, 0),
        (8, 15, 1),
        (17, 23, 2),
    ]


def test_sentence_indices_are_recomputed_not_copied_from_phrasplit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "Hello. World."
    _fake_phrasplit(
        monkeypatch,
        [
            SimpleNamespace(
                char_start=0, char_end=6, text="Hello.", paragraph_idx=50, sentence_idx=70
            ),
            SimpleNamespace(
                char_start=7, char_end=13, text="World.", paragraph_idx=50, sentence_idx=71
            ),
        ],
    )

    topology = build_sentence_topology(
        text,
        (_run(0, len(text)),),
        (),
        tokens=(),
        token_providers=(),
    )

    assert [
        (text[item.start : item.end], item.paragraph_index, item.sentence_index)
        for item in topology.sentences
    ] == [
        ("Hello.", 0, 0),
        ("World.", 0, 1),
    ]
    assert [
        (part.paragraph_index, part.sentence_index, part.part_index) for part in topology.parts
    ] == [
        (0, 0, 0),
        (0, 1, 0),
    ]


def test_sentence_spans_cross_language_runs_without_run_edge_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "Hello bonjour."
    _fake_phrasplit(monkeypatch)

    topology = build_sentence_topology(
        text,
        (_run(0, 6, "run-1", "en"), _run(6, len(text), "run-2", "fr")),
        (),
        tokens=(),
        token_providers=(),
    )

    assert [(text[item.start : item.end], item.sentence_index) for item in topology.sentences] == [
        (text, 0)
    ]


def test_sentence_parts_keep_semicolon_colon_and_fullwidth_separator_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_phrasplit(monkeypatch)
    cases = (
        ("Hello; world.", ["Hello; ", "world."]),
        ("Wait: I know.", ["Wait: ", "I know."]),
        ("等等：我知道。", ["等等：", "我知道。"]),
        ("Hello; ; world.", ["Hello; ; ", "world."]),
        ('She said: "hello" and left.', ["She said: ", '"hello" and left.']),
    )
    for text, expected_parts in cases:
        topology = build_sentence_topology(
            text,
            (_run(0, len(text)),),
            (),
            tokens=(),
            token_providers=(),
        )
        assert [text[part.start : part.end] for part in topology.parts] == expected_parts
        assert [part.part_index for part in topology.parts] == list(range(len(expected_parts)))


def test_part_fallback_protects_numeric_colons_and_url_semicolons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "It is 12:30. Ratio 3:2 is stable. Visit https://example.com/a;b. Next."
    _fake_phrasplit(monkeypatch, error=RuntimeError("dependency failed"))
    topology = build_sentence_topology(
        text,
        (_run(0, len(text)),),
        (),
        tokens=(),
        token_providers=(),
    )
    assert [text[part.start : part.end] for part in topology.parts] == [
        "It is 12:30.",
        "Ratio 3:2 is stable.",
        "Visit https://example.com/a;b.",
        "Next.",
    ]


def test_optional_clause_candidates_create_sentence_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "I wanted to go, but it was raining."
    _fake_phrasplit(monkeypatch)
    topology = build_sentence_topology(
        text,
        (_run(0, len(text)),),
        (),
        tokens=(),
        token_providers=(),
        optional_part_boundaries=(SimpleNamespace(kind="clause", position=16),),
    )
    assert [text[part.start : part.end] for part in topology.parts] == [
        "I wanted to go, ",
        "but it was raining.",
    ]


def test_optional_parenthetical_candidates_remain_parts_without_losing_spaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "Text (aside) continues."
    _fake_phrasplit(monkeypatch)
    topology = build_sentence_topology(
        text,
        (_run(0, len(text)),),
        (),
        tokens=(),
        token_providers=(),
        optional_part_boundaries=(
            SimpleNamespace(kind="parenthetical", position=5),
            SimpleNamespace(kind="parenthetical", position=12),
        ),
    )
    assert [text[part.start : part.end] for part in topology.parts] == [
        "Text ",
        "(aside)",
        " continues.",
    ]


def test_unsafe_part_candidate_is_dropped_at_provider_token_edge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "alphabeta;tail."
    _fake_phrasplit(monkeypatch)
    topology = build_sentence_topology(
        text,
        (_run(0, len(text)),),
        (),
        tokens=(TokenAnnotation(0, len(text) - 1, "alphabeta;tail"),),
        token_providers=("spacy",),
    )
    assert [text[part.start : part.end] for part in topology.parts] == [text]
    assert any(item.code == "segmentation.part_candidate_dropped" for item in topology.repairs)


def test_quote_aware_fallback_attaches_closing_quote_to_sentence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "“Hello.” She replied."
    _fake_phrasplit(monkeypatch)

    topology = build_sentence_topology(
        text,
        (_run(0, len(text)),),
        (),
        tokens=(),
        token_providers=(),
    )

    assert [text[item.start : item.end] for item in topology.sentences] == [
        "“Hello.”",
        "She replied.",
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("Dr. Smith arrived. Next.", ["Dr. Smith arrived.", "Next."]),
        ("The value is 3.14. Next.", ["The value is 3.14.", "Next."]),
        ("Version 1.2.3 works. Next.", ["Version 1.2.3 works.", "Next."]),
        ("J. R. R. Tolkien wrote. Next.", ["J. R. R. Tolkien wrote.", "Next."]),
        ("U.S. Army arrived. Next.", ["U.S. Army arrived.", "Next."]),
        ("e.g. this is fine. Next.", ["e.g. this is fine.", "Next."]),
        ("中文第一句。中文第二句。", ["中文第一句。", "中文第二句。"]),
    ),
)
def test_conservative_fallback_protects_period_patterns_and_supports_unicode(
    monkeypatch: pytest.MonkeyPatch, text: str, expected: list[str]
) -> None:
    _fake_phrasplit(monkeypatch, error=RuntimeError("dependency failed"))

    topology = build_sentence_topology(
        text,
        (_run(0, len(text)),),
        (),
        tokens=(),
        token_providers=(),
    )

    assert [text[item.start : item.end] for item in topology.sentences] == expected
    assert topology.degraded


def test_unsafe_automatic_candidate_is_dropped_instead_of_snapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "lifecycle now"
    _fake_phrasplit(
        monkeypatch,
        [
            SimpleNamespace(char_start=0, char_end=4, text="life", paragraph_idx=0, sentence_idx=0),
            SimpleNamespace(
                char_start=4, char_end=len(text), text="cycle now", paragraph_idx=0, sentence_idx=1
            ),
        ],
    )
    token = TokenAnnotation(0, 9, "lifecycle")

    topology = build_sentence_topology(
        text,
        (_run(0, len(text)),),
        (),
        tokens=(token,),
        token_providers=("fallback",),
    )

    assert [text[item.start : item.end] for item in topology.sentences] == [text]
    assert topology.repairs[0].code == "segmentation.lexical_boundary_merged"


def test_non_whitespace_coverage_validator_rejects_missing_content() -> None:
    text = "Hello; world."
    segments = (
        SimpleNamespace(id="s1", spoken_start=0, spoken_end=5, text="Hello"),
        SimpleNamespace(id="s2", spoken_start=7, spoken_end=len(text), text="world."),
    )

    with pytest.raises(Exception) as exc_info:
        validate_non_whitespace_coverage(text, segments)

    assert getattr(exc_info.value, "code", None) == "segmentation.content_gap"


def test_seeded_fallback_fuzz_is_deterministic_and_covers_all_speech_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rng = random.Random(20251009)
    atoms = ("alpha", "Dr.", "3:2", "12:30", "中文", "https://example.com/a;b")
    separators = ("; ", ": ", "：", ". ", "? ", "… ", ", ")
    _fake_phrasplit(monkeypatch, error=RuntimeError("dependency failed"))

    for _ in range(60):
        text = rng.choice(atoms)
        for _ in range(rng.randint(2, 6)):
            text += rng.choice(separators) + rng.choice(atoms)
        text += rng.choice((".", "!", "。", "?”"))
        topology = build_sentence_topology(
            text,
            (_run(0, len(text)),),
            (),
            tokens=(),
            token_providers=(),
        )
        repeated = build_sentence_topology(
            text,
            (_run(0, len(text)),),
            (),
            tokens=(),
            token_providers=(),
        )
        assert topology == repeated
        assert all(contains_speech_content(text[part.start : part.end]) for part in topology.parts)
        for sentence in topology.sentences:
            sentence_parts = [
                part for part in topology.parts if part.sentence_index == sentence.sentence_index
            ]
            assert [part.part_index for part in sentence_parts] == list(range(len(sentence_parts)))
        validate_non_whitespace_coverage(
            text,
            tuple(
                SimpleNamespace(
                    id=f"part-{index}",
                    spoken_start=part.start,
                    spoken_end=part.end,
                    text=text[part.start : part.end],
                )
                for index, part in enumerate(topology.parts)
            ),
        )
