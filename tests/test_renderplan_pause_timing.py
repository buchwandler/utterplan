from __future__ import annotations

import pytest

from utterplan.model import TokenView
from utterplan.renderplan_pause_timing import (
    PauseTimingConfig,
    PauseTimingContext,
    PauseTimingDecision,
    resolve_automatic_pause_duration,
)


def _context(
    left: str = "Go.",
    right: str = "Tomorrow.",
    *,
    boundary: str = "sentence",
    language: str = "en",
    left_tokens: tuple[TokenView, ...] = (),
    right_tokens: tuple[TokenView, ...] = (),
    left_heading: int | None = None,
    right_heading: int | None = None,
) -> PauseTimingContext:
    return PauseTimingContext(
        boundary=boundary,
        language=language,
        left_text=left,
        right_text=right,
        left_tokens=left_tokens,
        right_tokens=right_tokens,
        left_heading=left_heading,
        right_heading=right_heading,
    )


def _duration(
    left: str,
    *,
    right: str = "Tomorrow.",
    mode: str = "engaging",
    language: str = "en",
    boundary: str = "sentence",
) -> PauseTimingDecision:
    return resolve_automatic_pause_duration(
        500, _context(left, right, language=language, boundary=boundary), PauseTimingConfig(mode)
    )


def test_fixed_preserves_baseline_for_every_context() -> None:
    contexts = (
        _context("Go.", "And then?"),
        _context("A very long sentence with lots of lexical words.", "But next."),
        _context("I thought…", "", boundary="paragraph", right_heading=1),
    )
    for context in contexts:
        decision = resolve_automatic_pause_duration(503, context, PauseTimingConfig())
        assert decision == PauseTimingDecision(503, 503, 1000, ("fixed",))


def test_short_and_long_groups_receive_different_deterministic_durations() -> None:
    short = _duration("Go.")
    long = _duration("The long complicated sentence finished after many words.")
    assert short.duration_ms < long.duration_ms
    assert short == _duration("Go.")
    assert all(decision.duration_ms % 10 == 0 for decision in (short, long))


def test_question_and_ellipsis_score_more_than_ordinary_period() -> None:
    period = _duration("Are you sure.")
    question = _duration("Are you sure?")
    ellipsis = _duration("Are you sure…")
    assert question.duration_ms > period.duration_ms
    assert ellipsis.duration_ms > question.duration_ms
    assert "punctuation:ellipsis:+160" in ellipsis.features


def test_continuation_connective_shortens_english_boundary() -> None:
    connective = _duration("A finished sentence.", right="And another sentence.")
    ordinary = _duration("A finished sentence.", right="Tomorrow another sentence.")
    assert connective.duration_ms < ordinary.duration_ms
    assert "connective:and:-90" in connective.features


def test_connective_uses_lemma_when_available() -> None:
    right_tokens = (TokenView(0, 5, lemma="and", pos="CCONJ"),)
    context = _context("A sentence.", "plus text", right_tokens=right_tokens)
    decision = resolve_automatic_pause_duration(500, context, PauseTimingConfig("engaging"))
    assert "connective:and:-90" in decision.features
    assert "pos:next-conjunction:-50" in decision.features


def test_pos_facts_are_optional_and_function_word_adjustments_apply() -> None:
    left = "We were waiting for"
    right = "and everyone arrived"
    no_pos = _duration(left, right=right)
    left_tokens = (
        TokenView(0, 2, lemma="we", pos="PRON"),
        TokenView(3, 7, lemma="be", pos="AUX"),
        TokenView(8, 15, lemma="wait", pos="VERB"),
        TokenView(16, 19, lemma="for", pos="ADP"),
    )
    right_tokens = (
        TokenView(0, 3, lemma="and", pos="CCONJ"),
        TokenView(4, 12, lemma="everyone", pos="PRON"),
    )
    with_pos = resolve_automatic_pause_duration(
        500,
        _context(left, right, left_tokens=left_tokens, right_tokens=right_tokens),
        PauseTimingConfig("engaging"),
    )
    assert with_pos.duration_ms < no_pos.duration_ms
    assert "pos:next-conjunction:-50+pos:final-function-word:-80" in with_pos.features


def test_pos_token_count_excludes_punctuation() -> None:
    text = "Go now."
    tokens = (
        TokenView(0, 2, lemma="go", pos="VERB"),
        TokenView(3, 6, lemma="now", pos="ADV"),
        TokenView(6, 7, pos="PUNCT"),
    )
    decision = resolve_automatic_pause_duration(
        500, _context(text, left_tokens=tokens), PauseTimingConfig("natural")
    )
    assert "length:tokens:2" in decision.features


def test_text_word_count_fallback_is_used_when_pos_is_unavailable() -> None:
    tokens = (TokenView(0, 2), TokenView(3, 6), TokenView(6, 7))
    decision = resolve_automatic_pause_duration(
        500,
        _context("Go now.", left_tokens=tokens),
        PauseTimingConfig("natural"),
    )
    assert "length:text:2" in decision.features


def test_english_connective_table_is_not_applied_to_other_languages() -> None:
    english = _duration("A sentence.", right="And another.", language="en-US")
    french = _duration("A sentence.", right="And another.", language="fr")
    assert english.duration_ms < french.duration_ms
    assert not any(feature.startswith("connective:") for feature in french.features)


@pytest.mark.parametrize("boundary", ["clause", "sentence", "paragraph"])
def test_adaptive_factor_stays_within_boundary_clamps(boundary: str) -> None:
    low_context = _context(
        "Go,",
        "and",
        boundary=boundary,
        left_tokens=(TokenView(0, 2, pos="ADP"),),
        right_tokens=(TokenView(0, 3, pos="SCONJ"),),
    )
    high_text = " ".join(["word"] * 30) + "…"
    high_context = _context(high_text, "next", boundary=boundary, right_heading=1)
    for mode in ("natural", "engaging"):
        low = resolve_automatic_pause_duration(500, low_context, PauseTimingConfig(mode))
        high = resolve_automatic_pause_duration(500, high_context, PauseTimingConfig(mode))
        limits = {
            "natural": {"clause": (750, 1250), "sentence": (760, 1200), "paragraph": (820, 1180)},
            "engaging": {"clause": (600, 1150), "sentence": (600, 1150), "paragraph": (700, 1120)},
        }
        minimum, maximum = limits[mode][boundary]
        assert low.factor_permille == minimum
        assert high.factor_permille == maximum


def test_heading_transition_increases_structural_pause() -> None:
    ordinary = _duration("A complete sentence.", boundary="paragraph")
    heading = resolve_automatic_pause_duration(
        500,
        _context("A complete sentence.", boundary="paragraph", right_heading=2),
        PauseTimingConfig("natural"),
    )
    assert heading.duration_ms > ordinary.duration_ms
    assert heading.features[-1] == "heading:transition:+120"


def test_zero_baseline_voice_change_and_unknown_boundary_are_not_adapted() -> None:
    context = _context("An unusually long sentence…", boundary="sentence")
    zero = resolve_automatic_pause_duration(0, context, PauseTimingConfig("engaging"))
    voice = resolve_automatic_pause_duration(
        503,
        _context("An unusually long sentence…", boundary="voice_change"),
        PauseTimingConfig("engaging"),
    )
    other = resolve_automatic_pause_duration(
        503,
        _context("An unusually long sentence…", boundary="parenthetical"),
        PauseTimingConfig("engaging"),
    )
    assert zero == PauseTimingDecision(0, 0, 1000, ("zero-base",))
    assert voice.duration_ms == 503
    assert other.duration_ms == 503


def test_config_rejects_unknown_mode_and_resolver_requires_integer_baseline() -> None:
    with pytest.raises(ValueError, match="unsupported pause timing mode"):
        PauseTimingConfig("dramatic")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="base_ms must be an integer"):
        resolve_automatic_pause_duration(500.0, _context(), PauseTimingConfig())  # type: ignore[arg-type]
