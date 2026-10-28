from dataclasses import replace
from types import SimpleNamespace

from tests.compiler_helpers import CompilerTestPlanner as UtterancePlanner
from utterplan import FlowUnit, LinguisticsConfig, PlannerConfig, SemanticBoundary, compile_document
from utterplan.hashing import (
    LEGACY_UNIT_HASH_SCHEMA,
    UNIT_HASH_SCHEMA,
    semantic_hash,
    unit_hash_payload,
    unit_hash_payload_from_serialized,
)


def test_diagnostics_toggle_does_not_change_semantic_plan_id():
    text = "One sentence. Two sentences."
    left = UtterancePlanner(PlannerConfig(language="en-us", diagnostics=True)).plan(text)
    right = UtterancePlanner(PlannerConfig(language="en-us", diagnostics=False)).plan(text)
    assert left.plan_id == right.plan_id


def test_marker_at_sentence_unit_boundary_has_one_owner():
    plan = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
        )
    ).plan("One. @mark Two.")
    memberships = [marker_id for unit in plan.units for marker_id in unit.marker_ids]
    assert memberships == [plan.markers[0].id]


def test_audio_source_and_occurrence_position_change_plan_and_unit_identity() -> None:
    planner = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
            text_preparation="identity",
        )
    )
    uri_a = "sfx:impact.knock?force=0.7&seed=42"
    uri_b = "sfx:impact.knock?force=0.9&seed=42"
    first = planner.plan(f'[]{{src="{uri_a}"}}Before. After.')
    changed_source = planner.plan(f'[]{{src="{uri_b}"}}Before. After.')
    moved = planner.plan(f'Before. []{{src="{uri_a}"}}After.')

    assert first.texts.spoken == changed_source.texts.spoken == moved.texts.spoken
    assert first.plan_id != changed_source.plan_id
    assert first.units[0].content_hash != changed_source.units[0].content_hash
    assert first.plan_id != moved.plan_id
    assert first.units[0].content_hash != moved.units[0].content_hash


def _unit_hash_view(plan, *, semantic_boundaries=(), unit_index=0):
    unit = plan.units[unit_index]
    segments_by_id = {segment.id: segment for segment in plan.segments}
    markers_by_id = {marker.id: marker for marker in plan.markers}
    return SimpleNamespace(
        spoken_start=unit.spoken_start,
        spoken_end=unit.spoken_end,
        segments=tuple(segments_by_id[item_id] for item_id in unit.segment_ids),
        marker_ids=unit.marker_ids,
        marker_values=tuple(markers_by_id[item_id] for item_id in unit.marker_ids),
        tokens=plan.tokens,
        semantic_boundaries=semantic_boundaries,
    )


def test_current_unit_hash_schema_is_v3_and_legacy_identifier_is_retained() -> None:
    assert UNIT_HASH_SCHEMA == "utterplan-unit-v3"
    assert LEGACY_UNIT_HASH_SCHEMA == "utterplan-unit-v2"


def test_semantic_boundary_position_and_kind_change_plan_identity() -> None:
    plan = UtterancePlanner(PlannerConfig(language="en-us", text_preparation="identity")).plan(
        "Alpha beta gamma."
    )
    boundary = SemanticBoundary("semantic-boundary-000000", 6, "clause")
    first = replace(plan, semantic_boundaries=(boundary,)).with_identity()
    moved = replace(
        plan,
        semantic_boundaries=(replace(boundary, position=7),),
    ).with_identity()
    retyped = replace(
        plan,
        semantic_boundaries=(replace(boundary, kind="parenthetical"),),
    ).with_identity()

    assert first.plan_id != plan.plan_id
    assert moved.plan_id != first.plan_id
    assert retyped.plan_id != first.plan_id


def test_semantic_boundary_changes_unit_hash_v3() -> None:
    plan = UtterancePlanner(PlannerConfig(language="en-us", text_preparation="identity")).plan(
        "Alpha beta gamma."
    )
    boundary = SemanticBoundary("semantic-boundary-000000", 6, "clause")
    baseline = unit_hash_payload(_unit_hash_view(plan))
    changed = unit_hash_payload(_unit_hash_view(plan, semantic_boundaries=(boundary,)))

    assert changed["semantic_boundaries"] == [{"kind": "clause", "position": 6}]
    assert semantic_hash(changed) != semantic_hash(baseline)


def test_boundary_origin_and_diagnostics_do_not_change_unit_hash() -> None:
    plan = UtterancePlanner(PlannerConfig(language="en-us", text_preparation="identity")).plan(
        "Alpha beta gamma."
    )
    left = SemanticBoundary(
        "semantic-boundary-000000",
        6,
        "clause",
        origin="phrasplit",
        attrs={"detector_start": 5},
    )
    right = SemanticBoundary(
        "semantic-boundary-999999",
        6,
        "clause",
        origin="other-provider",
        attrs={"detector_start": 999},
    )

    assert unit_hash_payload(
        _unit_hash_view(plan, semantic_boundaries=(left,))
    ) == unit_hash_payload(_unit_hash_view(plan, semantic_boundaries=(right,)))


def test_boundary_at_unit_endpoint_does_not_change_unit_hash() -> None:
    plan = UtterancePlanner(PlannerConfig(language="en-us", text_preparation="identity")).plan(
        "Alpha beta gamma."
    )
    end = plan.units[0].spoken_end
    endpoint = SemanticBoundary("semantic-boundary-000000", end, "sentence")

    assert unit_hash_payload(_unit_hash_view(plan)) == unit_hash_payload(
        _unit_hash_view(plan, semantic_boundaries=(endpoint,))
    )


def test_semantic_boundary_outside_unit_does_not_change_that_unit_hash() -> None:
    plan = UtterancePlanner(PlannerConfig(language="en-us", text_preparation="identity")).plan(
        "First sentence.\n\nSecond sentence has more words."
    )
    second_unit = plan.units[1]
    outside = SemanticBoundary("semantic-boundary-000000", second_unit.spoken_start + 5, "clause")

    assert unit_hash_payload(_unit_hash_view(plan, unit_index=0)) == unit_hash_payload(
        _unit_hash_view(plan, semantic_boundaries=(outside,), unit_index=0)
    )


def test_unit_hash_v3_uses_relative_semantic_boundary_position() -> None:
    plan = UtterancePlanner(PlannerConfig(language="en-us", text_preparation="identity")).plan(
        "First sentence.\n\nSecond sentence has more words."
    )
    unit = plan.units[1]
    boundary = SemanticBoundary(
        "semantic-boundary-000000",
        unit.spoken_start + 5,
        "clause",
    )

    payload = unit_hash_payload(
        _unit_hash_view(plan, semantic_boundaries=(boundary,), unit_index=1)
    )

    assert payload["semantic_boundaries"] == [{"kind": "clause", "position": 5}]


def test_serialized_and_runtime_unit_hash_payloads_match() -> None:
    plan = UtterancePlanner(PlannerConfig(language="en-us", text_preparation="identity")).plan(
        "Alpha beta gamma."
    )
    boundary = SemanticBoundary("semantic-boundary-000000", 6, "clause")
    runtime_payload = unit_hash_payload(_unit_hash_view(plan, semantic_boundaries=(boundary,)))
    serialized_plan = plan.to_dict()
    serialized_plan["semantic_boundaries"] = [boundary.to_dict()]
    serialized_unit = plan.units[0].to_dict()

    migrated_payload = unit_hash_payload_from_serialized(serialized_unit, serialized_plan)

    assert migrated_payload == runtime_payload


def test_derived_say_as_changes_identity_and_v7_roundtrips_without_hashing_provenance() -> None:
    source = 'Because someone called [ART]{sub="A R T"} finally.'
    plan = compile_document(
        source,
        input_format="ssmd",
        config=PlannerConfig(
            language="en-us",
            document_format="ssmd",
            linguistics=LinguisticsConfig(use_spacy=False),
        ),
    ).plan
    assert "".join(segment.text for unit in plan.flow for segment in unit.segments) == (
        "Because someone called A R T finally."
    )
    spelled_ref = next(
        (unit_index, segment_index, segment)
        for unit_index, unit in enumerate(plan.flow)
        for segment_index, segment in enumerate(unit.segments)
        if segment.text == "A R T"
    )
    unit_index, segment_index, spelled = spelled_ref
    assert spelled.directives.say_as is not None
    assert spelled.directives.say_as.interpret_as == "characters"

    without_units = []
    for unit in plan.flow:
        without_units.append(
            FlowUnit(
                tuple(
                    replace(
                        segment,
                        directives=replace(segment.directives, say_as=None),
                    )
                    for segment in unit.segments
                )
            )
        )
    without_say_as = replace(plan, flow=tuple(without_units), plan_id="")
    assert without_say_as.flow[unit_index].segments[segment_index].text == spelled.text
    assert without_say_as.flow[unit_index].content_hash != plan.flow[unit_index].content_hash
    assert without_say_as.plan_id != plan.plan_id

    replacement = spelled.replacements[0]
    provenance_only = replace(replacement, source="different diagnostic spelling")
    changed_segments = list(plan.flow[unit_index].segments)
    changed_segments[segment_index] = replace(spelled, replacements=(provenance_only,))
    changed_units = list(plan.flow)
    changed_units[unit_index] = FlowUnit(tuple(changed_segments))
    provenance_changed = replace(plan, flow=tuple(changed_units), plan_id="")
    assert provenance_changed.flow[unit_index].content_hash == plan.flow[unit_index].content_hash
    assert provenance_changed.plan_id == plan.plan_id

    restored = type(plan).from_toml(plan.to_toml())
    assert restored == plan
    assert restored.schema_version == 7
    assert restored.flow[unit_index].segments[segment_index].directives.say_as == (
        spelled.directives.say_as
    )
