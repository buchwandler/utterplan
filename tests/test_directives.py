from __future__ import annotations

import jsonschema

from utterplan import PlannerConfig, UtterancePlanner
from utterplan.format import schema


def _planner() -> UtterancePlanner:
    return UtterancePlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
            text_preparation="identity",
        )
    )


def _directives(text: str, *, header: str = ""):
    source = f'---\nssmd_version: "0.9"\n{header}---\n{text}' if header else text
    plan = _planner().plan(source)
    return plan, plan.segments


def test_voice_selector_preserves_reference_and_features() -> None:
    _plan, segments = _directives(
        '[Hello]{voice="narrator" voice-name="Joanna" voice-languages="en-GB" gender="female" age="30" variant="2"}'
    )
    voice = segments[0].directives.voice

    assert voice is not None
    assert voice.reference == "narrator"
    assert voice.name == "Joanna"
    assert voice.languages == "en-GB"
    assert voice.gender == "female"
    assert voice.age == 30
    assert voice.variant == 2


def test_feature_only_voice_selector_is_valid() -> None:
    _plan, segments = _directives('[Hello]{voice-name="Joanna" gender="female" variant="2"}')
    voice = segments[0].directives.voice

    assert voice is not None
    assert voice.reference is None
    assert voice.name == "Joanna"
    assert voice.gender == "female"
    assert voice.variant == 2


def test_voice_defaults_are_effective_but_not_materialized_into_annotations() -> None:
    header = """voice_defaults:
  host:
    rate: slow
    pitch: high
"""
    plan, segments = _directives(':::{voice="host"}\nHello.\n:::', header=header)
    segment = segments[0]

    assert segment.directives.voice.reference == "host"
    assert segment.directives.prosody.rate == "slow"
    assert segment.directives.prosody.pitch == "high"
    voice_annotation = next(item for item in plan.annotations if item.attrs.get("voice") == "host")
    assert "rate" not in voice_annotation.attrs
    assert "pitch" not in voice_annotation.attrs


def test_prosody_inherits_per_field_and_inline_values_win() -> None:
    header = """voice_defaults:
  host:
    volume: soft
    rate: slow
    pitch: low
"""
    source = ':::{voice="host" rate="medium" volume="loud"}\nOuter [inner]{pitch="high" rate="fast"} text.\n:::'
    _plan, segments = _directives(source, header=header)
    inner = next(segment for segment in segments if segment.text.strip() == "inner")

    assert inner.directives.prosody.volume == "loud"
    assert inner.directives.prosody.rate == "fast"
    assert inner.directives.prosody.pitch == "high"


def test_nested_scope_order_keeps_narrower_prosody_values() -> None:
    _plan, segments = _directives(':::{rate="slow"}\n[inner]{pitch="high" rate="fast"}\n:::')
    inner = next(segment for segment in segments if segment.text.strip() == "inner")

    assert inner.directives.prosody.rate == "fast"
    assert inner.directives.prosody.pitch == "high"


def test_canonical_pronunciation_is_typed() -> None:
    _plan, segments = _directives('[word]{ph="wɜːd" alphabet="ipa"}')
    pronunciation = segments[0].directives.pronunciation

    assert pronunciation is not None
    assert pronunciation.phonemes == "wɜːd"
    assert pronunciation.alphabet == "ipa"


def test_say_as_is_typed() -> None:
    _plan, segments = _directives('[31.12.2024]{as="date" format="dd.mm.yyyy" detail="1"}')
    say_as = segments[0].directives.say_as

    assert say_as is not None
    assert say_as.interpret_as == "date"
    assert say_as.format == "dd.mm.yyyy"
    assert say_as.detail == "1"


def test_substitution_keeps_declared_text_and_types_alias() -> None:
    _plan, segments = _directives('[H2O]{sub="water"}')
    segment = segments[0]

    assert segment.text == "H2O"
    assert segment.directives.substitution.alias == "water"


def test_canonical_audio_attributes_and_fractional_repeat_are_typed() -> None:
    _plan, segments = _directives(
        '[Fallback]{src="clip.mp3" desc="Door chime" clip="1s-3s" speed="120%" repeat="1.5" level="-3dB"}'
    )
    segment = segments[0]
    audio = segment.directives.audio

    assert audio is not None
    assert audio.src == "clip.mp3"
    assert audio.description == "Door chime"
    assert audio.clip_begin == "1s"
    assert audio.clip_end == "3s"
    assert audio.speed == "120%"
    assert audio.repeat_count == 1.5
    assert audio.sound_level == "-3dB"
    assert segment.directives.emphasis is None


def test_audio_annotation_text_remains_spoken_fallback() -> None:
    _plan, segments = _directives('[Fallback]{src="clip.wav" desc="Door chime"}')

    assert segments[0].text == "Fallback"
    assert segments[0].directives.audio.description == "Door chime"


def test_extension_name_and_parameters_are_preserved() -> None:
    _plan, segments = _directives('[whispered text]{ext="whisper" amount="soft" mode="quiet"}')
    extensions = segments[0].directives.extensions

    assert len(extensions) == 1
    assert extensions[0].name == "whisper"
    assert extensions[0].params == {"amount": "soft", "mode": "quiet"}


def test_nested_extensions_compose_outer_to_inner() -> None:
    _plan, segments = _directives('[outer [inner]{ext="inner"}]{ext="outer"}')
    inner = next(segment for segment in segments if segment.text.strip() == "inner")
    assert [extension.name for extension in inner.directives.extensions] == ["outer", "inner"]


def test_new_directive_models_round_trip_through_plan_json() -> None:
    plan, _segments = _directives(
        '[Hello]{voice-name="Joanna"} [word]{ph="wɜːd" alphabet="ipa"} '
        '[bold]{emphasis="strong"} [date]{as="date" format="ymd"} '
        '[H2O]{sub="replacement"} [Fallback]{src="clip.wav" desc="sound" repeat="1.5"} '
        '[whispered]{ext="whisper" amount="soft"}'
    )

    assert type(plan).from_json(plan.to_json()) == plan
    jsonschema.validate(plan.to_dict(), schema())
