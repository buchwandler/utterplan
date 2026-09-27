from utterplan import PauseConfig, PlannerConfig, UtterancePlanner


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
            unit="sentence",
            pauses=PauseConfig(mode="manual"),
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
