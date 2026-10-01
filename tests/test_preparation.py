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


def test_zero_width_audio_annotation_maps_to_spoken_point():
    source = 'Before. []{src="clip.wav"} After.'
    plan = UtterancePlanner(PlannerConfig(language="en-us", document_format="ssmd")).plan(source)
    annotation = next(item for item in plan.annotations if item.attrs.get("src") == "clip.wav")

    assert annotation.structural_start == annotation.structural_end
    assert annotation.spoken_start == annotation.spoken_end
    assert plan.texts.spoken[annotation.spoken_start : annotation.spoken_end] == ""


def test_author_speech_annotations_are_protected_and_keep_source_offsets():
    source = (
        '[H2O]{sub="water"} '
        '[31.12.2024]{as="date" format="dd.mm.yyyy"} '
        '[04/05/2024]{say-as="date" format="MM/dd/yyyy"} '
        '[tomato]{ph="təˈmeɪtoʊ"} '
        '[AWS]{phonemes="eɪ dʌbəljuː ɛs"} ordinary 5 kg.'
    )
    plan = UtterancePlanner(PlannerConfig(language="en-us", document_format="ssmd")).plan(source)

    assert plan.texts.spoken == ("H2O 31.12.2024 04/05/2024 tomato AWS ordinary five kilograms.")
    protected = [
        annotation
        for annotation in plan.annotations
        if any(key in annotation.attrs for key in ("sub", "as", "say-as", "ph", "phonemes"))
    ]
    assert len(protected) == 5
    for annotation in protected:
        structural = plan.texts.structural[annotation.structural_start : annotation.structural_end]
        spoken = plan.texts.spoken[annotation.spoken_start : annotation.spoken_end]
        assert spoken == structural

    assert any(annotation.attrs.get("sub") == "water" for annotation in protected)
    assert any(annotation.attrs.get("as") == "date" for annotation in protected)
    assert any(annotation.attrs.get("say-as") == "date" for annotation in protected)
    assert any("ph" in annotation.attrs for annotation in protected)
    assert any("phonemes" in annotation.attrs for annotation in protected)

    assert len(plan.preparation.replacements) == 1
    replacement = plan.preparation.replacements[0]
    assert plan.texts.structural[replacement["source_start"] : replacement["source_end"]] == "5 kg"
    assert (
        plan.texts.spoken[replacement["output_start"] : replacement["output_end"]]
        == "five kilograms"
    )
