from __future__ import annotations

import pytest

from utterplan import (
    AnnotationSpan,
    BoundaryEvent,
    PlannerConfig,
    PlanRenderabilityError,
    PlanSegment,
    UtterancePlanner,
    classify_segment,
    preflight_renderability,
)
from utterplan.config import PauseConfig
from utterplan.planner import _repair_renderer_segments


def _segment(
    segment_id: str,
    text: str,
    start: int,
    end: int,
    *,
    language: str = "en-US",
) -> PlanSegment:
    return PlanSegment(
        id=segment_id,
        text=text,
        spoken_start=start,
        spoken_end=end,
        language=language,
        structural_start=start,
        structural_end=end,
    )


def _punctuation_issue(segment: PlanSegment, index: int = 1):
    issue = classify_segment(segment, index)
    assert issue is not None
    assert issue.code == "renderability.punctuation_only"
    return issue


def test_repair_drops_isolated_punctuation_and_records_guarantee() -> None:
    config = PlannerConfig(
        language="en-US",
        text_preparation="identity",
        renderability_mode="repair",
    )
    plan = UtterancePlanner(config).plan("Hello.\n\n.\n\nWorld.")

    repeated = UtterancePlanner(config).plan("Hello.\n\n.\n\nWorld.")
    assert repeated.plan_id == plan.plan_id
    assert repeated.to_json() == plan.to_json()
    assert [segment.text for segment in plan.segments] == ["Hello.", "World."]
    report = preflight_renderability(plan)
    assert report.ok
    assert plan.document_metadata["planning"]["renderability"] == {
        "mode": "repair",
        "checked_segments": 3,
        "repair_count": 1,
        "guaranteed": True,
    }
    repairs = [item for item in plan.diagnostics if item.code == "planning.renderability.repaired"]
    assert len(repairs) == 1
    assert repairs[0].message == "Removed isolated punctuation-only renderer segment '.'"
    assert repairs[0].line == 3
    assert plan.texts.spoken == "Hello.\n\n.\n\nWorld."


def test_safe_merge_uses_canonical_text_and_revalidates() -> None:
    lexical = _segment("seg-000000", "Hello", 0, 5)
    punctuation = _segment("seg-000001", ".", 5, 6)
    issue = _punctuation_issue(punctuation)

    repaired, repairs = _repair_renderer_segments(
        [lexical, punctuation], (issue,), "Hello.", [], PauseConfig(), ()
    )

    assert len(repaired) == 1
    assert repaired[0].text == "Hello."
    assert (repaired[0].spoken_start, repaired[0].spoken_end) == (0, 6)
    assert repairs[0].repair == "merge_neutral_punctuation"
    assert preflight_renderability(
        type("Plan", (), {"segments": tuple(repaired), "tokens": ()})()
    ).ok


def test_repair_never_merges_across_active_pause_and_preserves_boundary() -> None:
    lexical = _segment("seg-000000", "Hello", 0, 5)
    punctuation = _segment("seg-000001", ".", 5, 6)
    issue = _punctuation_issue(punctuation)
    boundary = BoundaryEvent(
        id="boundary-000000",
        position=5,
        kind="explicit",
        seconds=0.5,
        origin="ssmd",
        strength="sentence",
    )
    boundaries = [boundary]

    repaired, repairs = _repair_renderer_segments(
        [lexical, punctuation], (issue,), "Hello.", boundaries, PauseConfig(), ()
    )

    assert [segment.text for segment in repaired] == ["Hello"]
    assert repairs[0].repair == "drop_non_speech_punctuation"
    assert boundaries == [boundary]


def test_repair_does_not_merge_across_language_change() -> None:
    french = _segment("seg-fr", "bonjour", 0, 7, language="fr-FR")
    punctuation = _segment("seg-punc", ".", 7, 8, language="en-US")
    issue = _punctuation_issue(punctuation)

    repaired, repairs = _repair_renderer_segments(
        [french, punctuation], (issue,), "bonjour.", [], PauseConfig(), ()
    )

    assert [segment.text for segment in repaired] == ["bonjour"]
    assert repairs[0].repair == "drop_non_speech_punctuation"


def test_audio_instruction_at_join_prevents_merge_and_drop() -> None:
    lexical = _segment("seg-000000", "Hello", 0, 5)
    punctuation = _segment("seg-000001", ".", 5, 6)
    issue = _punctuation_issue(punctuation)
    audio = AnnotationSpan(
        id="annotation-audio",
        kind="audio",
        attrs={"tag": "audio", "src": "clip.wav"},
        structural_start=5,
        structural_end=5,
        spoken_start=5,
        spoken_end=5,
    )

    with pytest.raises(PlanRenderabilityError) as error:
        _repair_renderer_segments(
            [lexical, punctuation], (issue,), "Hello.", [], PauseConfig(), (audio,)
        )

    assert error.value.mode == "repair"
    assert error.value.issues[0].code == "renderability.repair_failed"


def test_symbol_only_content_fails_both_modes() -> None:
    for mode in ("strict", "repair"):
        config = PlannerConfig(
            language="en-US",
            text_preparation="identity",
            renderability_mode=mode,
        )
        with pytest.raises(PlanRenderabilityError) as error:
            UtterancePlanner(config).plan("€")
        assert error.value.issues[0].code == "renderability.symbol_only"
        assert error.value.mode == mode
