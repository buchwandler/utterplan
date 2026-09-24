from __future__ import annotations

import math

import pytest

from utterplan import PauseConfig, PlannerConfig, UtterancePlan, UtterancePlanner


def _fake_renderer(plan: UtterancePlan) -> None:
    segment_by_id = {segment.id: segment for segment in plan.segments}
    annotation_by_id = {annotation.id: annotation for annotation in plan.annotations}
    marker_by_id = {marker.id: marker for marker in plan.markers}
    assert plan.texts.spoken == plan.to_dict()["texts"]["spoken"]
    for run in plan.languages:
        assert run.language and run.spoken_end >= run.spoken_start
    for token in plan.tokens:
        assert plan.texts.spoken[token.spoken_start : token.spoken_end] == token.text
    for annotation in plan.annotations:
        assert annotation.id in annotation_by_id
    for boundary in plan.boundaries:
        assert boundary.position >= 0
    for segment in plan.segments:
        assert segment.id in segment_by_id
        _ = segment.directives.to_dict()
        _ = segment.pause_before.seconds + segment.pause_after.seconds
        for token_index in segment.token_indices:
            _ = plan.tokens[token_index].text
        for annotation_id in segment.annotation_ids:
            _ = annotation_by_id[annotation_id].attrs
    for marker in plan.markers:
        assert marker.id in marker_by_id
    for unit in plan.units:
        _ = [segment_by_id[segment_id].text for segment_id in unit.segment_ids]
        _ = [marker_by_id[marker_id].name for marker_id in unit.marker_ids]
    _ = plan.document_metadata


def assert_public_consumer_contract(plan: UtterancePlan) -> None:
    segments = {segment.id: segment for segment in plan.segments}
    annotations = {annotation.id: annotation for annotation in plan.annotations}
    markers = {marker.id: marker for marker in plan.markers}
    assert len(segments) == len(plan.segments)
    preparation = plan.to_dict()["preparation"]
    assert "offset_map" not in preparation
    assert "source_text" not in preparation
    assert "spoken_text" not in preparation

    for segment in plan.segments:
        assert segment.text == plan.texts.spoken[segment.spoken_start : segment.spoken_end]
        assert segment.language
        assert all(token_index < len(plan.tokens) for token_index in segment.token_indices)
        assert all(annotation_id in annotations for annotation_id in segment.annotation_ids)
        assert math.isfinite(segment.pause_before.seconds)
        assert math.isfinite(segment.pause_after.seconds)
        assert segment.pause_before.seconds >= 0
        assert segment.pause_after.seconds >= 0

    for unit in plan.units:
        assert all(segment_id in segments for segment_id in unit.segment_ids)
        assert all(marker_id in markers for marker_id in unit.marker_ids)

    restored = UtterancePlan.from_json(plan.to_json())
    assert restored == plan
    assert restored.texts.spoken == plan.texts.spoken
    assert [segment.text for segment in restored.segments] == [
        segment.text for segment in plan.segments
    ]


def test_fake_renderer_cannot_mutate_completed_plan() -> None:
    plan = UtterancePlanner(PlannerConfig(language="en-us")).plan(
        """---
ssmd_version: "0.9"
voice_bindings:
  narrator: voice-a
---
One. @mark [Two]{voice="narrator"}."""
    )
    before = plan.to_json(indent=None)
    plan_id = plan.plan_id
    _fake_renderer(plan)
    assert plan.to_json(indent=None) == before
    assert plan.plan_id == plan_id


def test_plain_spokenform_consumer_contract() -> None:
    plan = UtterancePlanner(PlannerConfig(language="en-us")).plan("Dr. Smith has 5 kg.")
    assert plan.texts.spoken == "Doctor Smith has five kilograms."
    assert_public_consumer_contract(plan)


def test_multilingual_ssmd_consumer_contract() -> None:
    plan = UtterancePlanner(PlannerConfig(language="en-us", text_preparation="identity")).plan(
        'Hello [Bonjour]{lang="fr"}.'
    )
    assert {run.language for run in plan.languages} == {"en-us", "fr"}
    assert_public_consumer_contract(plan)


def test_voice_directive_and_document_binding_are_public() -> None:
    text = """---
ssmd_version: "0.9"
voice_bindings:
  narrator: voice-a
---
[Hello]{voice="narrator"}."""
    plan = UtterancePlanner(PlannerConfig(language="en-us", text_preparation="identity")).plan(text)
    assert plan.document_metadata["voice_bindings"] == {"narrator": "voice-a"}
    assert plan.segments[0].directives.voice.reference == "narrator"
    assert_public_consumer_contract(plan)


def test_explicit_break_is_a_public_boundary() -> None:
    plan = UtterancePlanner(PlannerConfig(language="en-us", text_preparation="identity")).plan(
        "Hello ...c world"
    )
    assert any(boundary.kind == "explicit" for boundary in plan.boundaries)
    assert_public_consumer_contract(plan)


def test_automatic_semantic_pauses_are_resolved() -> None:
    plan = UtterancePlanner(PlannerConfig(language="en-us", pauses=PauseConfig(mode="auto"))).plan(
        "They changed clothes (stained with blood)."
    )
    parenthetical_ids = {event.id for event in plan.boundaries if event.kind == "parenthetical"}
    assert parenthetical_ids
    assert any(
        parenthetical_id in segment.pause_before.events + segment.pause_after.events
        for segment in plan.segments
        for parenthetical_id in parenthetical_ids
    )
    assert_public_consumer_contract(plan)


def test_medial_parenthetical_consumer_contract_preserves_pause_ownership():
    text = "The backup battery (still warm from the morning test) sat beside the console."
    plan = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            text_preparation="identity",
            pauses=PauseConfig(mode="auto"),
        )
    ).plan(text)

    assert [segment.text for segment in plan.segments] == [
        "The backup battery ",
        "(still warm from the morning test)",
        " sat beside the console.",
    ]
    assert_public_consumer_contract(plan)


@pytest.mark.parametrize("unit", ["paragraph", "sentence"])
def test_markers_and_unit_ownership_are_public(unit: str) -> None:
    plan = UtterancePlanner(
        PlannerConfig(language="en-us", unit=unit, text_preparation="identity")
    ).plan("One. @mark Two.")
    assert plan.markers
    owned = [marker_id for item in plan.units for marker_id in item.marker_ids]
    assert owned == [plan.markers[0].id]
    assert_public_consumer_contract(plan)
