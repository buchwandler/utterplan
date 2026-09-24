from utterplan import PlannerConfig, UtterancePlanner


def test_multilingual_preparation_composes_run_offsets():
    plan = UtterancePlanner(PlannerConfig(language="en-us", document_format="ssmd")).plan(
        'Hello [Bonjour]{lang="fr"}.'
    )
    assert plan.texts.spoken == "Hello Bonjour."
    assert [(run.language, run.spoken_start, run.spoken_end) for run in plan.languages] == [
        ("en-us", 0, 5),
        ("fr", 5, 13),
        ("en-us", 13, 14),
    ]
    assert plan.preparation.languages == ("en-us", "fr", "en-us")
    payload = plan.to_dict()
    assert "offset_map" not in payload["preparation"]
    assert "source_text" not in payload["preparation"]
    assert "spoken_text" not in payload["preparation"]
    for replacement in plan.preparation.replacements:
        assert (
            plan.texts.structural[replacement["source_start"] : replacement["source_end"]]
            == replacement["source"]
        )
        assert (
            plan.texts.spoken[replacement["output_start"] : replacement["output_end"]]
            == replacement["replacement"]
        )


def test_pronunciation_annotation_is_protected_and_resolved():
    plan = UtterancePlanner(PlannerConfig(language="en-us", document_format="ssmd")).plan(
        '[tomato]{ph="təˈmeɪtoʊ"}'
    )
    assert plan.texts.spoken == "tomato"
    assert plan.segments[0].directives.pronunciation.phonemes == "təˈmeɪtoʊ"


def test_header_pause_default_and_event_anchor_are_preserved():
    text = """---
ssmd_version: "0.9"
pause_defaults:
  sentence: 0.45
---
Hello ...s world"""
    plan = UtterancePlanner(PlannerConfig(language="en-us", document_format="ssmd")).plan(text)
    event = next(event for event in plan.boundaries if event.kind == "explicit")
    assert event.seconds == 0.45
    assert event.attrs["anchor"] == "after"
    assert event.attrs["pause_origin"] == "header_default"


def test_zero_break_is_not_a_paragraph_event():
    plan = UtterancePlanner(PlannerConfig(language="en-us", document_format="ssmd")).plan(
        "Hello ...0ms world"
    )
    assert any(event.kind == "explicit" and event.seconds == 0.0 for event in plan.boundaries)
    assert not any(event.kind == "paragraph" for event in plan.boundaries)
