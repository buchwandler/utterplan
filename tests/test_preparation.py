import sys

import pytest
import spokenform

from utterplan import PlannerConfig, UtterancePlanner
from utterplan.exceptions import PlanFormatError


def _record_sequence_fallback_modes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    modes: list[str] = []
    prepare = spokenform.prepare

    def record(text, **kwargs):
        modes.append(kwargs["sequence_fallback_mode"])
        return prepare(text, **kwargs)

    monkeypatch.setattr(spokenform, "prepare", record)
    return modes


@pytest.mark.parametrize(
    ("setting", "expected"),
    [
        ("", "spell"),
        ("sequence_fallback_mode: spell\n", "spell"),
        ("sequence_fallback_mode: preserve\n", "preserve"),
    ],
)
def test_sequence_fallback_mode_is_forwarded(
    setting: str, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    modes = _record_sequence_fallback_modes(monkeypatch)
    source = f'---\nssmd_version: "0.9"\n{setting}---\nin-system'
    plan = UtterancePlanner(PlannerConfig(language="en-us", document_format="ssmd")).plan(source)

    assert modes == [expected]
    assert plan.document_metadata["sequence_fallback_mode"] == expected


def test_plain_input_forwards_spell_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    modes = _record_sequence_fallback_modes(monkeypatch)
    UtterancePlanner(PlannerConfig(language="en-us", document_format="plain")).plan("in-system")
    assert modes == ["spell"]


@pytest.mark.parametrize("value", ["unknown", "null"])
def test_invalid_sequence_fallback_mode_fails_before_spokenform(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("spokenform.prepare must not run for invalid metadata")

    monkeypatch.setattr(spokenform, "prepare", fail_if_called)
    source = f'---\nssmd_version: "0.9"\nsequence_fallback_mode: {value}\n---\nin-system'

    with pytest.raises(PlanFormatError) as error:
        UtterancePlanner(PlannerConfig(language="en-us", document_format="ssmd")).plan(source)
    assert error.value.code == "header.sequence_fallback_mode_invalid"


def test_identity_preparation_keeps_sequence_fallback_mode_without_spokenform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "spokenform", None)
    source = '---\nssmd_version: "0.9"\nsequence_fallback_mode: preserve\n---\nin-system'
    plan = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
            text_preparation="identity",
        )
    ).plan(source)

    assert plan.texts.spoken == "in-system"
    assert plan.document_metadata["sequence_fallback_mode"] == "preserve"


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
