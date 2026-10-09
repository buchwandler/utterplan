from __future__ import annotations

from pathlib import Path

from utterplan import FlowPlan, PlannerConfig, compile_document
from utterplan.compiler import PreparationTrace
from utterplan.explain import format_explanation

GOLDEN = Path(__file__).parent / "golden"


def _migrated(name: str) -> FlowPlan:
    return FlowPlan.from_toml((GOLDEN / name).read_text(encoding="utf-8"))


def test_basic_explanation_is_human_oriented_and_current_schema() -> None:
    output = format_explanation(_migrated("basic_en.utterplan.toml"))

    assert "UtterPlan explanation" in output
    assert "schema: 5" in output
    assert "default language: en-us" in output
    assert "result: 1 unit, 1 segment" in output
    assert '1. [en-us] "Hello."' in output
    assert "No warnings." in output
    assert "Compiler provenance is not stored in the plan" in output
    assert "sha256:" not in output


def test_explanation_details_use_segment_local_token_coordinates() -> None:
    output = format_explanation(_migrated("basic_en.utterplan.toml"), details=True)

    assert "plan id: sha256:" in output
    assert "local tokens: 1" in output
    assert '0:6 "Hello."' in output
    assert "flow hash: sha256:" in output


def test_semantic_pauses_preserve_timed_and_explicit_none_intent() -> None:
    output = format_explanation(_migrated("ssmd_breaks.utterplan.toml"))

    assert "pause timed 500ms" in output
    assert "pause none" in output
    assert "0.50 s" not in output


def test_directives_are_humanized() -> None:
    output = format_explanation(_migrated("directives.utterplan.toml"))

    assert "effective prosody: rate 1.2, pitch +2st, volume 80%" in output
    assert "emphasis: strong" in output
    assert "{'prosody'" not in output


def test_multilingual_segments_remain_in_render_order() -> None:
    output = format_explanation(_migrated("multilingual.utterplan.toml"))

    labels = [output.index(label) for label in ("[en-us]", "[fr]")]
    assert labels[0] < labels[1]
    assert output.count("[en-us]") == 1
    assert '[fr] "Bonjour."' in output


def test_markers_are_shown_in_their_owning_flow_unit() -> None:
    output = format_explanation(_migrated("markers.utterplan.toml"))

    assert "Unit 2" in output
    assert "markers: @mark" in output
    assert output.index("Unit 2") < output.index("markers: @mark")


def test_compiler_trace_is_optional_and_does_not_change_executable_plan() -> None:
    text = "Dr. bought 5 kg."
    config = PlannerConfig(language="en-us", document_format="plain")
    without_trace = compile_document(text, input_format="plain", config=config)
    with_trace = compile_document(text, input_format="plain", config=config, trace=True)

    assert with_trace.trace is not None
    assert with_trace.plan.to_toml() == without_trace.plan.to_toml()
    assert "Compiler provenance is not stored" in format_explanation(with_trace.plan)
    explained = format_explanation(with_trace.plan, details=True, trace=with_trace.trace)
    assert "Preparation trace" in explained
    assert "backend: spokenform" in explained
    assert '"Dr." ->' in explained and '"Doctor"' in explained
    assert "source hash: " in explained


def test_trace_diagnostics_include_source_evidence() -> None:
    text = '---\nssmd_version: "0.9"\nunknown: true\n---\nHello.'
    result = compile_document(
        text,
        input_format="ssmd",
        config=PlannerConfig(language="en-us", document_format="ssmd"),
        trace=True,
    )
    assert result.trace is not None

    output = format_explanation(result.plan, trace=result.trace)

    assert "header.unknown_key [warn]" in output
    assert "line 3, column 1" in output


def test_trace_toml_round_trip_preserves_all_provenance() -> None:
    result = compile_document(
        "Dr. bought 5 kg.",
        input_format="plain",
        config=PlannerConfig(language="en-us", document_format="plain"),
        trace=True,
    )
    assert result.trace is not None

    restored = PreparationTrace.from_toml(result.trace.to_toml())

    assert restored.to_dict() == result.trace.to_dict()


def test_explanation_is_deterministic() -> None:
    plan = _migrated("directives.utterplan.toml")

    assert format_explanation(plan) == format_explanation(plan)
    assert format_explanation(plan, details=True) == format_explanation(plan, details=True)
