from __future__ import annotations

import pytest

from tests.compiler_helpers import CompilerTestPlanner as UtterancePlanner
from utterplan import PauseIntent, PlannerConfig
from utterplan.exceptions import PlanningError
from utterplan.model import BoundaryEvent, PlanSegment
from utterplan.pauses import resolve_edge_semantics

TEXT = "The backup battery (still warm from the morning test) sat beside the console."


def _planner() -> UtterancePlanner:
    return UtterancePlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
            text_preparation="identity",
        )
    )


def test_sentence_and_paragraph_boundaries_are_present_without_pause_policy():
    plan = _planner().plan("One sentence. Two sentences.\n\nSecond paragraph.")
    assert plan.segments[0].boundary_after == ("sentence",)
    assert plan.segments[1].boundary_after == ("paragraph",)
    assert all(segment.pause_after is None for segment in plan.segments)


def test_parenthetical_opportunities_are_present_without_pause_policy():
    plan = _planner().plan(TEXT)
    aside, resumed = plan.segments[1:]
    assert aside.boundary_before == ("parenthetical",)
    assert resumed.boundary_before == ("parenthetical",)
    assert aside.pause_before is None
    assert resumed.pause_before is None


def test_authored_none_coexists_with_sentence_boundary():
    plan = _planner().plan("Hello. ...n World.")
    first = next(segment for segment in plan.segments if segment.text == "Hello.")
    assert first.boundary_after == ("sentence",)
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
def test_ssmd_break_tokens_are_preserved_exactly(break_token: str, expected: PauseIntent):
    plan = _planner().plan(f"Hello. {break_token} World.")
    first = next(segment for segment in plan.segments if segment.text == "Hello.")
    assert first.pause_after == expected


def test_pause_defaults_do_not_materialize_automatic_pause_intents():
    source = """---
ssmd_version: "0.9"
pause_defaults:
  sentence: 800ms
---
One. Two."""
    plan = _planner().plan(source)
    assert plan.segments[0].boundary_after == ("sentence",)
    assert plan.segments[0].pause_after is None


def test_automatic_collisions_preserve_independent_boundary_facts():
    segment = PlanSegment("segment", "Hello", 0, 5, "en-us")
    events = [
        BoundaryEvent("clause", 5, "clausal_comma", attrs={"automatic": True}),
        BoundaryEvent("sentence", 5, "sentence", attrs={"automatic": True}),
        BoundaryEvent("paragraph", 5, "paragraph", attrs={"automatic": True}),
        BoundaryEvent("voice", 5, "voice_change", attrs={"automatic": True}),
    ]
    resolved = resolve_edge_semantics([segment], events)[0]
    assert resolved.boundary_after == ("paragraph", "voice_change")
    assert resolved.pause_after is None


def test_authored_strength_and_timed_break_coexist_with_sentence_opportunity():
    segment = PlanSegment("segment", "Hello", 0, 5, "en-us")
    sentence = BoundaryEvent("sentence", 5, "sentence", attrs={"automatic": True})
    strength = BoundaryEvent(
        "strength",
        5,
        "explicit",
        origin="ssmd",
        strength="medium",
        attrs={"anchor": "after", "pause_origin": "explicit", "strength": "medium"},
    )
    timed = BoundaryEvent(
        "timed",
        5,
        "explicit",
        origin="ssmd",
        attrs={"anchor": "after", "pause_origin": "explicit", "time": "500ms"},
    )

    with_strength = resolve_edge_semantics([segment], [sentence, strength])[0]
    with_timing = resolve_edge_semantics([segment], [sentence, timed])[0]
    assert with_strength.boundary_after == ("sentence",)
    assert with_strength.pause_after == PauseIntent("medium")
    assert with_timing.boundary_after == ("sentence",)
    assert with_timing.pause_after == PauseIntent("timed", "500ms")


def test_multiple_authored_breaks_at_one_edge_fail_instead_of_collapsing():
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
        resolve_edge_semantics([segment], breaks)


def test_authored_timed_break_is_preserved_without_pause_policy():
    plan = _planner().plan("Hello. ...500ms World.")
    first = next(segment for segment in plan.segments if segment.text == "Hello.")
    assert first.boundary_after == ("sentence",)
    assert first.pause_after == PauseIntent("timed", "500ms")


def test_unit_content_hash_tracks_semantic_content():
    first = UtterancePlanner(PlannerConfig(language="en-us")).plan("One.")
    second = UtterancePlanner(PlannerConfig(language="en-us")).plan("Two.")
    assert first.units[0].content_hash != second.units[0].content_hash
    first.validate()
    second.validate()
