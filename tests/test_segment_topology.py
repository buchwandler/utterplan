from __future__ import annotations

import unicodedata
from pathlib import Path

from tests.compiler_helpers import CompilerTestPlanner as UtterancePlanner
from utterplan import PauseIntent, PlannerConfig, classify_segment
from utterplan.model import AudioDirective, PlanSegment, SegmentDirectives, TokenAnnotation
from utterplan.planner import _is_neutral_punctuation_text


def _planner() -> UtterancePlanner:
    return UtterancePlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
            text_preparation="identity",
        )
    )


def _plan(source: str):
    return _planner().plan(source)


def _punctuation_only(text: str) -> bool:
    significant = [character for character in text if not character.isspace()]
    return bool(significant) and all(
        unicodedata.category(character).startswith("P") for character in significant
    )


def _assert_no_punctuation_only_speech(plan) -> None:
    assert [
        segment.text
        for segment in plan.segments
        if segment.directives.audio is None and _punctuation_only(segment.text)
    ] == []


def test_neutral_punctuation_excludes_symbols_and_emoji() -> None:
    assert _is_neutral_punctuation_text(".”")
    assert _is_neutral_punctuation_text(".)")
    assert not _is_neutral_punctuation_text("$")
    assert not _is_neutral_punctuation_text("€")
    assert not _is_neutral_punctuation_text("©")
    assert not _is_neutral_punctuation_text("™")
    assert not _is_neutral_punctuation_text("+")
    assert not _is_neutral_punctuation_text("🙂")


def test_renderability_classifier_reports_punctuation_tokens_but_accepts_audio() -> None:
    segment = PlanSegment(
        id="seg-punctuation",
        text=".)",
        spoken_start=4,
        spoken_end=6,
        language="en-us",
        token_indices=(0, 1),
    )
    tokens = (
        TokenAnnotation(4, 5, ".", pos="PUNCT", id="token-period"),
        TokenAnnotation(5, 6, ")", pos="PUNCT", id="token-close-paren"),
    )

    issue = classify_segment(segment, 0, tokens)

    assert issue is not None
    assert issue.code == "renderability.punctuation_only"
    assert issue.segment_id == "seg-punctuation"
    assert issue.spoken_start == 4 and issue.spoken_end == 6
    assert issue.text == ".)"
    assert issue.token_ids == ("token-period", "token-close-paren")
    assert issue.token_pos == ("PUNCT", "PUNCT")

    audio_segment = PlanSegment(
        id="seg-audio",
        text=".)",
        spoken_start=4,
        spoken_end=6,
        language="en-us",
        directives=SegmentDirectives(audio=AudioDirective(src="clip.wav")),
        token_indices=(0, 1),
    )
    assert classify_segment(audio_segment, 1, tokens) is None


def test_emphasis_period_is_one_segment_with_exact_annotation_range() -> None:
    plan = _plan('[Important]{emphasis="strong"}.')

    assert len(plan.segments) == 1
    segment = plan.segments[0]
    assert segment.text == "Important."
    assert segment.directives.emphasis.level == "strong"

    annotation = next(item for item in plan.annotations if item.attrs.get("emphasis"))
    assert annotation.spoken_start == 0
    assert annotation.spoken_end == len("Important")
    assert segment.spoken_end == len("Important.")


def test_supplied_emphasis_failure_shape_keeps_terminal_pause_on_speech() -> None:
    plan = _plan('Three said, [Initiate in 3–2–1]{emphasis="moderate"}. ...500ms')

    _assert_no_punctuation_only_speech(plan)
    final = next(segment for segment in plan.segments if "Initiate" in segment.text)
    assert final.text.rstrip().endswith(".")
    assert final.directives.emphasis.level == "moderate"
    assert final.pause_after == PauseIntent("timed", "500ms")

    annotation = next(item for item in plan.annotations if item.attrs.get("emphasis"))
    assert annotation.spoken_end < final.spoken_end


def test_pronunciation_period_keeps_override_span_exact() -> None:
    plan = _plan('[GIF]{ph="dʒɪf" alphabet="ipa"}.')

    assert len(plan.segments) == 1
    segment = plan.segments[0]
    assert segment.text == "GIF."
    assert segment.directives.pronunciation.phonemes == "dʒɪf"
    annotation = next(item for item in plan.annotations if item.attrs.get("ph"))
    assert annotation.spoken_start == 0
    assert annotation.spoken_end == 3
    assert segment.spoken_end == 4


def test_voice_transitions_attach_comma_and_period_to_speech() -> None:
    plan = _plan('[Hello]{voice="host"}, [world]{voice="guest"}.')

    _assert_no_punctuation_only_speech(plan)
    host, guest = plan.segments
    assert host.text == "Hello, "
    assert host.directives.voice.reference == "host"
    assert guest.text.strip() == "world."
    assert guest.directives.voice.reference == "guest"


def test_language_span_does_not_merge_lexical_content_across_languages() -> None:
    plan = _plan('He said [bonjour.]{lang="fr"}')

    _assert_no_punctuation_only_speech(plan)
    assert any(
        "He said" in segment.text and segment.language == "en-us" for segment in plan.segments
    )
    assert any("bonjour" in segment.text and segment.language == "fr" for segment in plan.segments)
    assert all(segment.language for segment in plan.segments)
    assert not any(
        "He said" in segment.text and "bonjour" in segment.text for segment in plan.segments
    )


def test_prosody_remains_on_speech_with_trailing_exclamation() -> None:
    plan = _plan('[Run now]{rate="fast"}!')

    assert len(plan.segments) == 1
    assert plan.segments[0].text == "Run now!"
    assert plan.segments[0].directives.prosody.rate == "fast"


def test_quotes_are_envelopes_not_standalone_renderer_segments() -> None:
    plan = _plan('"[Hello]{voice="guest"}"')

    _assert_no_punctuation_only_speech(plan)
    assert len(plan.segments) == 1
    assert plan.segments[0].text == '"Hello"'
    assert plan.segments[0].directives.voice.reference == "guest"


def test_parenthetical_closing_punctuation_is_not_a_segment() -> None:
    plan = _plan('She [left]{emphasis="strong"}.)')

    _assert_no_punctuation_only_speech(plan)
    assert any(segment.text.rstrip().endswith(".)") for segment in plan.segments)


def test_explicit_pause_stays_between_speech_segments() -> None:
    plan = _plan('[Stop]{emphasis="strong"}. ...500ms Continue.')

    _assert_no_punctuation_only_speech(plan)
    stop = next(segment for segment in plan.segments if "Stop" in segment.text)
    following = next(segment for segment in plan.segments if "Continue" in segment.text)
    assert stop.text.rstrip().endswith(".")
    assert stop.pause_after == PauseIntent("timed", "500ms")
    assert stop.spoken_end <= following.spoken_start
    assert stop.id != following.id


def test_audio_adjacent_speech_remains_atomic_and_renderable() -> None:
    plan = _plan('[Fallback]{src="clip.wav"} [After]{voice="guest"}.')

    audio_segments = [segment for segment in plan.segments if segment.directives.audio is not None]
    assert len(audio_segments) == 1
    assert audio_segments[0].text == "Fallback"
    _assert_no_punctuation_only_speech(plan)
    assert any(
        "After" in segment.text and segment.text.rstrip().endswith(".") for segment in plan.segments
    )


def test_audio_boundary_keeps_fallback_atomic_and_attaches_punctuation_forward() -> None:
    plan = _plan('[Fallback]{src="clip.wav"}.[After]{voice="guest"}')

    audio_segments = [segment for segment in plan.segments if segment.directives.audio is not None]
    assert len(audio_segments) == 1
    assert audio_segments[0].text == "Fallback"
    speech = next(segment for segment in plan.segments if "After" in segment.text)
    assert speech.text == ".After"
    assert speech.directives.voice.reference == "guest"
    _assert_no_punctuation_only_speech(plan)


def test_rich_ssmd_fixture_has_no_punctuation_only_speech_segments() -> None:
    fixture = Path(__file__).parent / "fixtures" / "ssmd_09_comprehensive.ssmd"
    plan = _planner().plan(fixture.read_text(encoding="utf-8"))

    _assert_no_punctuation_only_speech(plan)
