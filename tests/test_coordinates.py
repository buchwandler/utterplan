from utterplan import PlannerConfig, UtterancePlanner


def test_spokenform_mapping_keeps_structural_and_spoken_ranges_distinct():
    source = '[Dr. Smith bought 5 kg on Jan. 4.]{emphasis="moderate"}'
    plan = UtterancePlanner(PlannerConfig(language="en-us", document_format="ssmd")).plan(source)
    assert plan.texts.structural != plan.texts.spoken
    annotation = plan.annotations[0]
    assert (annotation.structural_start, annotation.structural_end) == (0, 32)
    assert (annotation.spoken_start, annotation.spoken_end) == (0, len(plan.texts.spoken))
    assert (annotation.source_start, annotation.source_end) == (0, len(source))
    assert plan.texts.spoken[annotation.spoken_start : annotation.spoken_end] == plan.texts.spoken


def test_marker_after_replacement_maps_to_spoken_position():
    plan = UtterancePlanner(PlannerConfig(language="en-us", document_format="ssmd")).plan(
        "Dr. @mark Smith."
    )
    assert plan.texts.spoken == "Doctor Smith."
    assert plan.markers[0].spoken_position == len("Doctor")


def test_identity_mapping_is_exact():
    text = "One. Two."
    plan = UtterancePlanner(
        PlannerConfig(language="en-us", document_format="plain", text_preparation="identity")
    ).plan(text)
    assert plan.texts.structural == plan.texts.spoken == text
    for annotation in plan.annotations:
        assert annotation.spoken_start == annotation.structural_start
        assert annotation.spoken_end == annotation.structural_end


def test_segment_membership_uses_spoken_ranges():
    plan = UtterancePlanner(PlannerConfig(language="en-us")).plan("Doctor bought 5 kg.")
    assert plan.tokens
    assert all(
        index < len(plan.tokens) for segment in plan.segments for index in segment.token_indices
    )
