from utterplan import PlannerConfig, UtterancePlanner

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
        'Hello [Bonjour]{lang="fr"}.'
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
    assert [(event.position, event.kind) for event in plan.boundaries] == [(14, "paragraph")]
