from __future__ import annotations

from dataclasses import replace

import pytest

from utterplan import (
    CompileResult,
    PlannerConfig,
    PreparationTrace,
    PreparationTraceUnit,
    UtterancePlanner,
    compile_document,
)
from utterplan.exceptions import ConfigurationError


def test_public_compile_api_uses_document_language_and_returns_diagnostics() -> None:
    config = PlannerConfig(language="en-us", text_preparation="identity")
    source = '---\nssmd_version: "0.9"\nlanguage: de-DE\n---\nHallo.'

    result = compile_document(
        source,
        input_format="ssmd",
        config=config,
        fallback_language="fr-FR",
    )

    assert isinstance(result, CompileResult)
    assert result.trace is None
    assert result.diagnostics == result.plan.diagnostics
    assert {segment.language for segment in result.plan.segments} == {"de-DE"}
    assert result.plan.config["language"] == "fr-FR"


def test_public_compile_api_handles_plain_text_and_legacy_api_matches() -> None:
    config = PlannerConfig(language="en-us", text_preparation="identity")
    result = compile_document("Hello.", input_format="plain", config=config)
    legacy = UtterancePlanner(config).plan("Hello.")

    assert result.plan == legacy
    assert result.plan.source.format == "plain"
    assert result.diagnostics == legacy.diagnostics


def test_public_compile_api_validates_input_format_and_fallback() -> None:
    config = PlannerConfig(language="en-us")
    with pytest.raises(ConfigurationError, match="input_format"):
        compile_document("Hello.", input_format="book", config=config)  # type: ignore[arg-type]
    with pytest.raises(ConfigurationError, match="fallback_language"):
        compile_document("Hello.", config=config, fallback_language=" ")


def test_trace_models_are_public_immutable_contract_types() -> None:
    assert PreparationTrace.__dataclass_params__.frozen
    assert PreparationTraceUnit.__dataclass_params__.frozen


def test_optional_trace_explains_preparation_without_changing_plan_identity() -> None:
    config = PlannerConfig(language="en-us", text_preparation="spokenform")
    text = '---\nssmd_version: "0.9"\nsequence_fallback_mode: preserve\n---\nDr. Smith has 5 kg.'

    ordinary = compile_document(text, input_format="ssmd", config=config)
    explained = compile_document(text, input_format="ssmd", config=config, trace=True)

    assert ordinary.trace is None
    assert explained.trace is not None
    assert explained.plan.plan_id == ordinary.plan.plan_id
    assert explained.trace.document_language == "en-us"
    assert explained.trace.sequence_fallback_mode == "preserve"
    assert explained.trace.diagnostics == explained.plan.diagnostics
    assert len(explained.trace.units) == 1
    unit = explained.trace.units[0]
    assert unit.source_start == 0
    assert unit.source_end == len("Dr. Smith has 5 kg.")
    assert unit.source_text == "Dr. Smith has 5 kg."
    assert unit.prepared_text == explained.plan.texts.spoken
    assert unit.effective_language == "en-us"
    assert unit.effective_languages == ("en-us",)
    assert unit.split_reason == "paragraph segmentation"
    assert unit.transformations
    assert any(change.source == "Dr." for change in unit.transformations)


def test_trace_source_ranges_follow_sentence_units_after_text_expansion() -> None:
    text = "Dr. Smith has 5 kg. Second sentence."
    config = PlannerConfig(language="en-us", unit="sentence")
    result = compile_document(text, input_format="plain", config=config, trace=True)

    assert result.trace is not None
    assert [unit.source_text for unit in result.trace.units] == [
        "Dr. Smith has 5 kg.",
        "Second sentence.",
    ]
    assert result.trace.units[0].prepared_text == "Doctor Smith has five kilograms."
    assert result.trace.units[0].source_start == 0
    assert result.trace.units[0].source_end == len("Dr. Smith has 5 kg.")
    assert result.trace.units[1].source_start == len("Dr. Smith has 5 kg. ")
    assert result.trace.units[1].source_end == len(text)
    assert result.trace.units[1].transformations == ()


def test_plan_identity_is_repeatable_and_tracks_semantic_metadata() -> None:
    config = PlannerConfig(language="en-us", text_preparation="identity")
    source = '---\nssmd_version: "0.9"\nlanguage: en-US\n---\nHello.'
    first = compile_document(source, input_format="ssmd", config=config).plan
    second = compile_document(source, input_format="ssmd", config=config).plan

    assert first.plan_id == second.plan_id
    changed = replace(
        first,
        document_metadata={
            **first.document_metadata,
            "requires": {"extensions": ["acme.effects.whisper"]},
        },
    ).with_identity()
    assert changed.plan_id != first.plan_id


def test_renderer_only_settings_are_absent_from_the_semantic_plan() -> None:
    plan = compile_document(
        "Hello.",
        input_format="plain",
        config=PlannerConfig(language="en-us", text_preparation="identity"),
    ).plan
    forbidden = {"engine", "model", "kokoro_model", "piper_model", "sample_rate", "output_filename"}

    assert forbidden.isdisjoint(plan.config)
    assert forbidden.isdisjoint(plan.semantic_dict()["config"])
    assert forbidden.isdisjoint(plan.semantic_dict()["document_metadata"])
