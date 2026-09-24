from utterplan import PauseConfig, PlannerConfig, UtterancePlanner


def test_plain_sentences_paragraphs_and_pauses():
    value = "One sentence. Two sentences.\n\nSecond paragraph."
    plan = UtterancePlanner(PlannerConfig(language="EN_US", document_format="plain")).plan(value)
    assert plan.source.text == value
    assert plan.texts.structural == value
    assert plan.texts.spoken == value
    assert len(plan.segments) == 3
    assert len(plan.units) == 2
    assert plan.segments[0].pause_after.seconds == 0.6
    assert plan.segments[1].pause_after.seconds == 1.0


def test_ssmd_preparation_and_explicit_directives():
    plan = UtterancePlanner(PlannerConfig(language="en-us", document_format="ssmd")).plan(
        '[tomato]{ph="təˈmeɪtoʊ"}'
    )
    assert plan.preparation.backend == "spokenform"
    assert plan.segments[0].directives.pronunciation.phonemes == "təˈmeɪtoʊ"


def test_ssmd_break_marker_and_language():
    plan = UtterancePlanner(PlannerConfig(language="en-us", document_format="ssmd")).plan(
        'Hello ...500ms [Bonjour]{lang="fr"} @mark'
    )
    assert len(plan.segments) >= 2
    assert any(run.language == "fr" for run in plan.languages)
    assert plan.markers[0].name == "mark"
    assert any(segment.pause_after.seconds == 0.5 for segment in plan.segments)


def test_identity_is_deterministic():
    config = PlannerConfig(language="de_DE", text_preparation="identity")
    left = UtterancePlanner(config).plan("Hallo.")
    right = UtterancePlanner(config).plan("Hallo.")
    assert left == right
    assert left.plan_id == right.plan_id


def test_pause_config_default_is_tts():
    assert PauseConfig().mode == "tts"


def test_pass_a_tokens_counts_tokens_not_language_runs():
    plan = UtterancePlanner(
        PlannerConfig(language="en-us", document_format="plain", text_preparation="identity")
    ).plan("One two three.")

    assert plan.document_metadata["planning"]["pass_a_tokens"] == 3
    assert plan.texts.spoken == "One two three."
