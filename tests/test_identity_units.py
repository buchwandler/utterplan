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
