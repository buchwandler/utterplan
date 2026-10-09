from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from utterplan import (
    CompileResult,
    PlannerConfig,
    PreparationTrace,
    PreparationTraceUnit,
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
    assert result.diagnostics
    assert {segment.language for unit in result.plan.flow for segment in unit.segments} == {"de-DE"}
    assert result.plan.language == "fr-FR"


def test_public_compile_api_handles_plain_text_and_legacy_api_matches() -> None:
    config = PlannerConfig(language="en-us", text_preparation="identity")
    result = compile_document("Hello.", input_format="plain", config=config)
    legacy = compile_document("Hello.", input_format="plain", config=config)

    assert result.plan == legacy.plan
    assert result.plan.document.format == "plain"
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
    assert explained.plan.to_toml() == ordinary.plan.to_toml()
    assert explained.plan.warnings == ordinary.plan.warnings == ()
    assert explained.trace.document_language == "en-us"
    assert explained.trace.sequence_fallback_mode == "preserve"
    assert explained.trace.source_text == text
    assert (
        explained.trace.source_sha256
        == "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    )
    assert explained.trace.spoken_text == "Doctor Smith has five kilograms."
    assert explained.trace.config["text_preparation"] == "spokenform"
    assert len(explained.trace.structural_to_spoken) == len(explained.trace.structural_text) + 1
    assert len(explained.trace.spoken_to_structural) == len(explained.trace.spoken_text) + 1
    assert explained.trace.source_spans
    assert explained.trace.compiler_plan["tokens"]
    assert explained.trace.renderability["checked_segments"] == 1
    assert not explained.trace.repairs
    assert explained.trace.diagnostics == explained.diagnostics
    assert len(explained.trace.units) == 1
    unit = explained.trace.units[0]
    assert unit.source_start == 0
    assert unit.source_end == len("Dr. Smith has 5 kg.")
    assert unit.source_text == "Dr. Smith has 5 kg."
    prepared_text = "".join(
        segment.text for flow_unit in explained.plan.flow for segment in flow_unit.segments
    )
    assert unit.prepared_text == prepared_text
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
        document=replace(
            first.document,
            semantics={
                **first.document.semantics,
                "requires": {"extensions": ["acme.effects.whisper"]},
            },
        ),
        plan_id="",
    )
    assert changed.plan_id != first.plan_id


def test_renderer_only_settings_are_absent_from_the_semantic_plan() -> None:
    plan = compile_document(
        "Hello.",
        input_format="plain",
        config=PlannerConfig(language="en-us", text_preparation="identity"),
    ).plan
    forbidden = {"engine", "model", "kokoro_model", "piper_model", "sample_rate", "output_filename"}

    payload = plan.to_dict()
    assert forbidden.isdisjoint(payload)
    assert forbidden.isdisjoint(payload["document"]["semantics"])
