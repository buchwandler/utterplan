from __future__ import annotations

import pytest

from tests.compiler_helpers import CompilerTestPlanner as UtterancePlanner
from utterplan import PauseConfig, PauseIntent, PlannerConfig
from utterplan.exceptions import PlanningError
from utterplan.model import BoundaryEvent, PlanSegment
from utterplan.pauses import resolve_pause_intents

TEXT = "The backup battery (still warm from the morning test) sat beside the console."


def _planner(*, mode: str = "tts", enabled: bool = True) -> UtterancePlanner:
    return UtterancePlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
            text_preparation="identity",
            pauses=PauseConfig(mode=mode, enabled=enabled),
        )
    )


def test_sentence_and_paragraph_pauses_are_semantic_in_every_mode() -> None:
    plan = UtterancePlanner(PlannerConfig(language="en-us")).plan(
        "One sentence. Two sentences.\n\nSecond paragraph."
    )
    assert plan.segments[0].pause_after == PauseIntent("sentence")
    assert plan.segments[1].pause_after == PauseIntent("paragraph")


def test_parenthetical_activation_respects_pause_mode_and_enabled_flag() -> None:
    text = "They changed out their clothes (stained with blood)."
    inactive = UtterancePlanner(
        PlannerConfig(language="en-us", text_preparation="identity", pauses=PauseConfig(mode="tts"))
    ).plan(text)
    active = UtterancePlanner(
        PlannerConfig(
            language="en-us", text_preparation="identity", pauses=PauseConfig(mode="auto")
        )
    ).plan(text)
    disabled = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            text_preparation="identity",
            pauses=PauseConfig(mode="auto", enabled=False),
        )
    ).plan(text)

    assert all(
        segment.pause_before is None and segment.pause_after is None
        for segment in inactive.segments
    )
    assert any(
        segment.pause_before == PauseIntent("parenthetical")
        or segment.pause_after == PauseIntent("parenthetical")
        for segment in active.segments
    )
    assert all(
        segment.pause_before is None and segment.pause_after is None
        for segment in disabled.segments
    )


def test_auto_parenthetical_pauses_attach_to_both_structural_edges() -> None:
    plan = UtterancePlanner(
        PlannerConfig(
            language="en-us", text_preparation="identity", pauses=PauseConfig(mode="auto")
        )
    ).plan(TEXT)
    assert [segment.text for segment in plan.segments] == [
        "The backup battery ",
        "(still warm from the morning test)",
        " sat beside the console.",
    ]
    aside, resumed = plan.segments[1:]
    assert aside.pause_before == PauseIntent("parenthetical")
    assert resumed.pause_before == PauseIntent("parenthetical")
    assert aside.pause_after is None
    assert resumed.pause_after is None


def test_parenthetical_semantics_coexist_with_paragraph_semantics() -> None:
    text = TEXT + "\n\nThe team continued the test."
    plan = UtterancePlanner(
        PlannerConfig(
            language="en-us", text_preparation="identity", pauses=PauseConfig(mode="auto")
        )
    ).plan(text)
    resumed = next(
        segment for segment in plan.segments if segment.text == " sat beside the console."
    )
    assert resumed.pause_before == PauseIntent("parenthetical")
    assert resumed.pause_after == PauseIntent("paragraph")


def test_authored_none_suppresses_automatic_sentence_pause() -> None:
    plan = _planner(mode="auto").plan("Hello. ...n World.")
    first = next(segment for segment in plan.segments if segment.text == "Hello.")
    assert first.pause_after == PauseIntent("none")


@pytest.mark.parametrize(
    ("break_token", "expected"),
    [
        ("...n", PauseIntent("none")),
        ("...w", PauseIntent("x-weak")),
        ("...c", PauseIntent("medium")),
        ("...s", PauseIntent("strong")),
        ("...p", PauseIntent("x-strong")),
        ("...500ms", PauseIntent("timed", "500ms")),
        ("...2s", PauseIntent("timed", "2s")),
    ],
)
def test_ssmd_break_tokens_are_preserved_exactly(break_token: str, expected: PauseIntent) -> None:
    plan = _planner(mode="auto").plan(f"Hello. {break_token} World.")
    first = next(segment for segment in plan.segments if segment.text == "Hello.")
    assert first.pause_after == expected


def test_pause_defaults_do_not_materialize_or_override_semantic_intent() -> None:
    source = """---
ssmd_version: "0.9"
pause_defaults:
  sentence: 800ms
---
One. Two."""
    plan = _planner(mode="auto").plan(source)
    assert plan.segments[0].pause_after == PauseIntent("sentence")
    assert plan.config["pauses"] == {"mode": "auto", "enabled": True}


def test_stale_ssmd_pause_override_configuration_is_rejected() -> None:
    with pytest.raises(TypeError, match="pause_overrides"):
        from utterplan import SSMDConfig

        SSMDConfig(pause_overrides={"sentence": "250ms"})  # type: ignore[call-arg]


def test_automatic_collision_uses_semantic_priority_without_durations() -> None:
    segment = PlanSegment("segment", "Hello", 0, 5, "en-us")
    events = [
        BoundaryEvent("comma", 5, "clausal_comma", attrs={"automatic": True}),
        BoundaryEvent("sentence", 5, "sentence", attrs={"automatic": True}),
        BoundaryEvent("paragraph", 5, "paragraph", attrs={"automatic": True}),
    ]
    resolved = resolve_pause_intents([segment], events, PauseConfig(mode="auto"))[0]
    assert resolved.pause_after == PauseIntent("paragraph")


def test_authored_strength_overrides_automatic_sentence_candidate() -> None:
    segment = PlanSegment("segment", "Hello", 0, 5, "en-us")
    events = [
        BoundaryEvent("sentence", 5, "sentence", attrs={"automatic": True}),
        BoundaryEvent(
            "break",
            5,
            "explicit",
            origin="ssmd",
            strength="medium",
            attrs={"anchor": "after", "pause_origin": "explicit", "strength": "medium"},
        ),
    ]
    resolved = resolve_pause_intents([segment], events, PauseConfig(mode="auto"))[0]
    assert resolved.pause_after == PauseIntent("medium")


def test_authored_timed_break_overrides_automatic_sentence_candidate() -> None:
    segment = PlanSegment("segment", "Hello", 0, 5, "en-us")
    events = [
        BoundaryEvent("sentence", 5, "sentence", attrs={"automatic": True}),
        BoundaryEvent(
            "break",
            5,
            "explicit",
            origin="ssmd",
            attrs={"anchor": "after", "pause_origin": "explicit", "time": "500ms"},
        ),
    ]
    resolved = resolve_pause_intents([segment], events, PauseConfig(mode="auto"))[0]
    assert resolved.pause_after == PauseIntent("timed", "500ms")


def test_multiple_authored_breaks_at_one_edge_fail_instead_of_collapsing() -> None:
    segment = PlanSegment("segment", "Hello", 0, 5, "en-us")
    breaks = [
        BoundaryEvent(
            f"break-{strength}",
            5,
            "explicit",
            origin="ssmd",
            strength=strength,
            attrs={"anchor": "after", "pause_origin": "explicit", "strength": strength},
        )
        for strength in ("weak", "strong")
    ]
    with pytest.raises(PlanningError, match="multiple authored"):
        resolve_pause_intents([segment], breaks, PauseConfig(mode="auto"))


def test_disabled_automatic_pause_keeps_explicit_authored_pause_active() -> None:
    plan = _planner(mode="auto", enabled=False).plan("Hello. ...500ms World.")
    first = next(segment for segment in plan.segments if segment.text == "Hello.")
    assert first.pause_after == PauseIntent("timed", "500ms")


def test_unit_content_hash_tracks_semantic_content() -> None:
    first = UtterancePlanner(PlannerConfig(language="en-us")).plan("One.")
    second = UtterancePlanner(PlannerConfig(language="en-us")).plan("Two.")
    assert first.units[0].content_hash != second.units[0].content_hash
    first.validate()
    second.validate()
