import pytest

from tests.compiler_helpers import CompilerTestPlanner as UtterancePlanner
from utterplan import BoundaryKind, FlowSegment, PauseIntent, PlannerConfig
from utterplan.boundaries import canonicalize_boundary_kinds, validate_canonical_boundary_kinds
from utterplan.model import PlanSegment

TEXT = "The backup battery (still warm from the morning test) sat beside the console."


def test_medial_parenthetical_boundaries_use_spoken_coordinates_and_anchors():
    plan = UtterancePlanner(PlannerConfig(language="en-us", text_preparation="identity")).plan(TEXT)
    opening = TEXT.index("(")
    closing = TEXT.index(")")
    events = [event for event in plan.boundaries if event.kind == "parenthetical"]

    assert [event.attrs["detected_kind"] for event in events] == [
        "parenthetical_open",
        "parenthetical_close",
    ]
    assert [event.position for event in events] == [opening, closing + 1]
    assert all(event.origin == "phrasplit" for event in events)
    assert all(event.attrs["automatic"] is True for event in events)
    assert all(event.attrs["anchor"] == "before" for event in events)
    semantic = [item for item in plan.semantic_boundaries if item.kind == "parenthetical"]
    assert [item.position for item in semantic] == [opening, closing + 1]
    assert [event.attrs["semantic_boundary_id"] for event in events] == [
        item.id for item in semantic
    ]


def test_parenthetical_boundary_keeps_phrasplit_origin():
    plan = UtterancePlanner(PlannerConfig(language="en-us")).plan(
        "They changed out their clothes (stained with blood)."
    )
    events = [event for event in plan.boundaries if event.kind == "parenthetical"]
    assert events
    assert all(event.origin == "phrasplit" for event in events)
    assert all(0 <= event.position <= len(plan.texts.spoken) for event in events)


def test_language_cut_does_not_invent_clausal_comma():
    plan = UtterancePlanner(PlannerConfig(language="en-us", document_format="ssmd")).plan(
        'Hello [Bonjour.]{lang="fr"}'
    )
    assert not any(event.kind == "clausal_comma" for event in plan.boundaries)


def test_explicit_ssmd_boundary_keeps_ssmd_origin():
    plan = UtterancePlanner(PlannerConfig(language="en-us", document_format="ssmd")).plan(
        "Hello ...c world"
    )
    event = next(event for event in plan.boundaries if event.kind == "explicit")
    assert event.origin == "ssmd"
    assert event.attrs["anchor"] == "after"


def test_derived_paragraph_boundary_does_not_duplicate_existing_event():
    plan = UtterancePlanner(PlannerConfig(language="en-us")).plan(
        "One paragraph.\n\nTwo paragraph."
    )
    keys = [(event.position, event.kind) for event in plan.boundaries]
    assert len(keys) == len(set(keys))
    assert [(item.position, item.kind) for item in plan.semantic_boundaries] == [(14, "paragraph")]
    assert [(event.position, event.kind) for event in plan.boundaries] == [(14, "paragraph")]


def test_boundary_kinds_are_canonicalized_on_internal_and_public_segments():
    kind: BoundaryKind = "clause"
    expected = ("sentence", "voice_change")
    values = ("voice_change", "sentence", "sentence")

    assert canonicalize_boundary_kinds((kind, "voice_change")) == ("clause", "voice_change")
    assert canonicalize_boundary_kinds(values) == expected
    assert canonicalize_boundary_kinds(("clause", "sentence", "paragraph", "voice_change")) == (
        "paragraph",
        "voice_change",
    )

    public = FlowSegment("Hello.", "en-US", boundary_after=values)
    assert public.boundary_after == expected
    assert public.to_dict()["boundary_after"] == list(expected)

    internal = PlanSegment("s1", "Hello.", 0, 6, "en-US", boundary_before=values)
    assert internal.boundary_before == expected
    assert internal.to_dict()["boundary_before"] == list(expected)

    authored_none = FlowSegment(
        "Hello.", "en-US", pause_after=PauseIntent("none"), boundary_after=("sentence",)
    )
    assert authored_none.pause_after == PauseIntent("none")
    assert authored_none.boundary_after == ("sentence",)
    assert authored_none.to_dict()["boundary_after"] == ["sentence"]
    assert authored_none.to_dict()["pause_after"] == "none"


def test_boundary_kind_validation_rejects_unknown_duplicate_and_noncanonical_values():
    with pytest.raises(ValueError, match="unsupported boundary kind"):
        canonicalize_boundary_kinds(("sentence", "engine_token"))
    with pytest.raises(ValueError, match="duplicates"):
        validate_canonical_boundary_kinds(("sentence", "sentence"))
    with pytest.raises(ValueError, match="canonical ordering"):
        validate_canonical_boundary_kinds(("voice_change", "sentence"))
    with pytest.raises(ValueError, match="weaker structural"):
        validate_canonical_boundary_kinds(("sentence", "paragraph"))
