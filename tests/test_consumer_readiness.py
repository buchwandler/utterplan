from __future__ import annotations

import pytest

from utterplan import PauseConfig, PlanFormatError, PlannerConfig, SSMDConfig, UtterancePlanner


def test_reusable_planner_isolates_request_configuration() -> None:
    base = PlannerConfig(
        language="en-us", document_format="plain", text_preparation="identity", unit="sentence"
    )
    alternate = PlannerConfig(
        language="de-de",
        document_format="plain",
        text_preparation="identity",
        unit="paragraph",
        pauses=PauseConfig(sentence="180ms"),
    )
    planner = UtterancePlanner(base)
    first = planner.plan("One. Two.", unit="sentence")
    second = planner.plan("Eins. Zwei.", config=alternate)
    third = planner.plan("One. Two.", unit="sentence")
    fresh = UtterancePlanner(base).plan("One. Two.", unit="sentence")
    assert first == fresh == third
    assert second.config["language"] == "de-de"
    assert second.config["pauses"]["sentence"] == 0.18
    assert planner.config == base
    planner.close()


def test_duration_spellings_have_equal_plan_identity() -> None:
    left = PlannerConfig(
        language="en-us",
        document_format="plain",
        text_preparation="identity",
        pauses=PauseConfig(sentence="500ms"),
    )
    right = PlannerConfig(
        language="en-us",
        document_format="plain",
        text_preparation="identity",
        pauses=PauseConfig(sentence=0.5),
    )
    assert (
        UtterancePlanner(left).plan("One. Two.").plan_id
        == UtterancePlanner(right).plan("One. Two.").plan_id
    )


def _ssmd_plan(text: str, **kwargs: object):
    config = PlannerConfig(language="en-us", text_preparation="identity", ssmd=SSMDConfig(**kwargs))
    return UtterancePlanner(config).plan(text)


def test_ssmd_unknown_header_uses_parser_diagnostic() -> None:
    plan = _ssmd_plan(
        """---
ssmd_version: "0.9"
unknown: true
---
Hello."""
    )
    diagnostic = next(item for item in plan.diagnostics if item.code == "header.unknown_key")

    assert diagnostic.severity == "warn"
    assert diagnostic.path == "$.source"
    assert diagnostic.line == 3
    assert diagnostic.source_start == plan.source.text.index("unknown")


def test_ssmd_header_malformed_yaml_is_public_error() -> None:
    with pytest.raises(PlanFormatError, match="header.yaml_invalid"):
        _ssmd_plan(
            """---
ssmd_version: "0.9"
pause_defaults: [
---
Hello."""
        )


def test_ssmd_parse_header_false_does_not_consume_front_matter() -> None:
    plan = _ssmd_plan(
        """---
ssmd_version: "0.9"
unknown: value
---
Hello.""",
        parse_header=False,
    )
    assert "unknown: value" in plan.texts.structural
    assert plan.document_metadata["header"] == {}


def test_pause_defaults_enabled_disables_automatic_document_pauses() -> None:
    plan = _ssmd_plan(
        """---
ssmd_version: "0.9"
pause_defaults:
  enabled: false
---
One. Two."""
    )
    assert all(
        segment.pause_before.seconds == 0 and segment.pause_after.seconds == 0
        for segment in plan.segments
    )


def test_voice_change_pause_uses_logical_voice_in_one_language() -> None:
    config = PlannerConfig(
        language="en-us", text_preparation="identity", pauses=PauseConfig(mode="auto")
    )
    plan = UtterancePlanner(config).plan('[One]{voice="a"} [Two]{voice="b"}.')
    voice_events = [event for event in plan.boundaries if event.kind == "voice_change"]
    assert voice_events
    assert any(
        event_id in plan.segments[0].pause_after.events
        for event_id in (event.id for event in voice_events)
    )


def test_prepared_contract_uses_spoken_coordinates_and_public_token_fields() -> None:
    source = 'Dr. Smith [has]{emphasis="moderate"} 5 kg.'
    plan = UtterancePlanner(PlannerConfig(language="en-us")).plan(source)
    assert plan.texts.spoken == "Doctor Smith has five kilograms."
    annotation = plan.annotations[0]
    assert annotation.spoken_start == 12
    assert annotation.spoken_end == 16
    assert annotation.source_start == source.index("[has")
    assert annotation.source_end == source.index("}") + 1
    assert all(token.spoken_end <= len(plan.texts.spoken) for token in plan.tokens)
    assert all(
        hasattr(token, field)
        for token in plan.tokens
        for field in ("text", "pos", "tag", "lemma", "language")
    )
    assert all(
        segment.text == plan.texts.spoken[segment.spoken_start : segment.spoken_end]
        for segment in plan.segments
    )


def test_voice_bindings_and_segment_logical_voice_remain_separate() -> None:
    text = """---
ssmd_version: "0.9"
voice_bindings:
  narrator: voice-a
---
[Hello]{voice="narrator"}."""
    plan = UtterancePlanner(PlannerConfig(language="en-us", text_preparation="identity")).plan(text)
    assert plan.document_metadata["voice_bindings"] == {"narrator": "voice-a"}
    assert plan.segments[0].directives.voice.reference == "narrator"
    assert plan.segments[0].directives.voice.reference != "voice-a"
    assert "offset_map" not in plan.to_dict()["preparation"]
    assert plan == type(plan).from_json(plan.to_json())


def test_language_detection_header_is_preserved_as_portable_metadata() -> None:
    text = """---
ssmd_version: "0.9"
language_detection:
  mode: auto
  languages: [de, en]
---
Hallo."""
    plan = UtterancePlanner(PlannerConfig(language="en-us")).plan(text)
    assert plan.document_metadata["language_detection"] == {
        "mode": "auto",
        "languages": ["de", "en"],
    }
    restored = type(plan).from_json(plan.to_json())
    assert restored.document_metadata == plan.document_metadata


@pytest.mark.parametrize(
    ("header", "code"),
    [
        ("language_detection: true", "header.language_detection_invalid"),
        (
            """language_detection:
  mode: auto
  languages: [de, 1]""",
            "header.language_detection_languages_invalid",
        ),
    ],
)
def test_language_detection_header_shape_is_validated(header: str, code: str) -> None:
    document = f"""---
{header}
---
Hallo."""
    with pytest.raises(PlanFormatError) as error:
        UtterancePlanner(PlannerConfig(language="en-us")).plan(document)
    assert error.value.code == code
