import pytest

from utterplan import PauseConfig, PlannerConfig, UtterancePlanner
from utterplan.model import BoundaryEvent, PlanSegment
from utterplan.pauses import resolve_pauses

TEXT = "The backup battery (still warm from the morning test) sat beside the console."


def test_pause_mode_keeps_sentence_and_paragraph_policy_deterministic():
    text = "One sentence. Two sentences.\n\nSecond paragraph."
    for mode in ("tts", "manual", "auto"):
        plan = UtterancePlanner(
            PlannerConfig(language="en-us", document_format="plain", pauses=PauseConfig(mode=mode))
        ).plan(text)
        assert plan.segments[0].pause_after.seconds == 0.6
        assert plan.segments[1].pause_after.seconds == 1.0


def test_automatic_parenthetical_pause_only_applies_in_auto_mode():
    text = "They changed out their clothes (stained with blood)."
    tts = UtterancePlanner(PlannerConfig(language="en-us", pauses=PauseConfig(mode="tts"))).plan(
        text
    )
    auto = UtterancePlanner(PlannerConfig(language="en-us", pauses=PauseConfig(mode="auto"))).plan(
        text
    )
    assert all(
        event_id not in {event.id for event in tts.boundaries if event.kind == "parenthetical"}
        for segment in tts.segments
        for event_id in segment.pause_before.events + segment.pause_after.events
    )
    assert any(
        event_id in {event.id for event in auto.boundaries if event.kind == "parenthetical"}
        for segment in auto.segments
        for event_id in segment.pause_before.events + segment.pause_after.events
    )


@pytest.mark.parametrize("mode", ["tts", "manual"])
def test_inactive_automatic_parentheticals_do_not_split_segments(mode: str):
    plan = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            text_preparation="identity",
            pauses=PauseConfig(mode=mode),
        )
    ).plan(TEXT)

    assert [segment.text for segment in plan.segments] == [TEXT]
    assert any(event.kind == "parenthetical" for event in plan.boundaries)
    assert all(
        not (segment.pause_before.events or segment.pause_after.events) for segment in plan.segments
    )


def test_disabled_automatic_parentheticals_do_not_split_segments():
    plan = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            text_preparation="identity",
            pauses=PauseConfig(mode="auto", enabled=False),
        )
    ).plan(TEXT)

    assert [segment.text for segment in plan.segments] == [TEXT]
    assert any(event.kind == "parenthetical" for event in plan.boundaries)


def test_auto_parenthetical_pauses_own_both_segment_edges():
    plan = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            text_preparation="identity",
            pauses=PauseConfig(mode="auto", parenthetical=0.15),
        )
    ).plan(TEXT)
    opening_event, closing_event = (
        event for event in plan.boundaries if event.kind == "parenthetical"
    )

    assert [segment.text for segment in plan.segments] == [
        "The backup battery ",
        "(still warm from the morning test)",
        " sat beside the console.",
    ]
    aside = plan.segments[1]
    resumed = plan.segments[2]
    assert aside.pause_before.seconds == pytest.approx(0.15)
    assert aside.pause_before.events == (opening_event.id,)
    assert resumed.pause_before.seconds == pytest.approx(0.15)
    assert resumed.pause_before.events == (closing_event.id,)
    assert not aside.pause_after.events
    assert not resumed.pause_after.events


def test_parenthetical_closing_pause_coexists_with_paragraph_pause():
    text = TEXT + "\n\nThe team continued the test."
    plan = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            text_preparation="identity",
            pauses=PauseConfig(mode="auto", parenthetical=0.15),
        )
    ).plan(text)
    resumed = next(
        segment for segment in plan.segments if segment.text == " sat beside the console."
    )

    assert resumed.pause_before.seconds == pytest.approx(0.15)
    assert resumed.pause_after.seconds == pytest.approx(1.0)


def test_explicit_ssmd_break_remains_active_when_automatic_pauses_are_disabled():
    plan = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
            text_preparation="identity",
            pauses=PauseConfig(mode="manual", enabled=False),
        )
    ).plan("Hello ...c world")

    event = next(event for event in plan.boundaries if event.kind == "explicit")
    assert event.attrs["anchor"] == "after"
    assert any(event.id in segment.pause_after.events for segment in plan.segments)


def test_default_pause_mode_remains_tts():
    assert PauseConfig().mode == "tts"


def test_high_confidence_clausal_comma_and_zero_duration_boundary_are_resolved() -> None:
    segment = PlanSegment("seg", "Hello", 0, 5, "en-us")
    boundaries = (
        BoundaryEvent(
            "comma",
            5,
            "clausal_comma",
            origin="phrasplit",
            attrs={"automatic": True, "confidence": "1.0"},
        ),
        BoundaryEvent(
            "zero",
            5,
            "explicit",
            seconds=0.0,
            origin="ssmd",
            attrs={"anchor": "after", "pause_origin": "explicit"},
        ),
    )
    resolved = resolve_pauses([segment], list(boundaries), PauseConfig(mode="auto"))[0]
    assert resolved.pause_after.seconds == pytest.approx(0.0)
    assert resolved.pause_after.events == ("comma", "zero")


def test_explicit_ssmd_break_precedes_automatic_pause_and_retains_provenance() -> None:
    segment = PlanSegment("seg", "Hello", 0, 5, "en-us")
    boundaries = (
        BoundaryEvent(
            "sentence",
            5,
            "sentence",
            seconds=0.6,
            origin="planner",
            attrs={"automatic": True},
        ),
        BoundaryEvent(
            "break",
            5,
            "explicit",
            seconds=0.2,
            origin="ssmd",
            attrs={"anchor": "after", "pause_origin": "explicit"},
        ),
    )
    resolved = resolve_pauses([segment], list(boundaries), PauseConfig(mode="auto"))[0]
    assert resolved.pause_after.seconds == pytest.approx(0.2)
    assert resolved.pause_after.events == ("break", "sentence")


def test_longest_default_pause_wins_without_explicit_break() -> None:
    segment = PlanSegment("seg", "Hello", 0, 5, "en-us")
    boundaries = (
        BoundaryEvent(
            "sentence",
            5,
            "sentence",
            seconds=0.6,
            origin="planner",
            attrs={"automatic": True},
        ),
        BoundaryEvent(
            "paragraph",
            5,
            "paragraph",
            seconds=1.0,
            origin="planner",
            attrs={"automatic": True},
        ),
    )
    resolved = resolve_pauses([segment], list(boundaries), PauseConfig(mode="auto"))[0]
    assert resolved.pause_after.seconds == pytest.approx(1.0)
    assert resolved.pause_after.events == ("paragraph", "sentence")


def test_unit_content_hash_tracks_semantic_content() -> None:
    first = UtterancePlanner(PlannerConfig(language="en-us")).plan("One.")
    second = UtterancePlanner(PlannerConfig(language="en-us")).plan("Two.")
    assert first.units[0].content_hash != second.units[0].content_hash
    first.validate()
    second.validate()
