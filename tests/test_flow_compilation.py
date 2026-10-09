from __future__ import annotations

import json
from pathlib import Path

import pytest

from utterplan import FlowPlan, PauseConfig, PlannerConfig, UtterancePlanner, compile_document
from utterplan.migrations.v4_to_v5 import migrate_v4_to_v5


def _segments(plan: FlowPlan):
    return tuple(segment for unit in plan.flow for segment in unit.segments)


def test_fresh_compile_returns_current_v5_local_flow() -> None:
    text = 'Hello [world]{emphasis="strong"}.'
    config = PlannerConfig(language="en-us", document_format="ssmd", text_preparation="identity")
    result = compile_document(text, input_format="ssmd", config=config)
    planner = UtterancePlanner(config)
    try:
        planned = planner.plan(text)
    finally:
        planner.close()

    assert isinstance(result.plan, FlowPlan)
    assert result.plan.schema_version == 5
    assert planned == result.plan
    payload = result.plan.to_toml()
    assert payload == result.plan.to_toml()
    assert FlowPlan.from_toml(payload) == result.plan
    assert not hasattr(result.plan, "tokens")
    assert not hasattr(result.plan, "segments")
    assert any(segment.directives.emphasis is not None for segment in _segments(result.plan))
    for segment in _segments(result.plan):
        assert all(segment.text[token.start : token.end] for token in segment.tokens)


@pytest.mark.parametrize(
    "fixture_name",
    ("basic_en", "ssmd_breaks", "markers", "multilingual", "parenthetical", "spokenform_offsets"),
)
def test_fresh_compilation_converges_with_v4_migration_on_unambiguous_input(
    fixture_name: str,
) -> None:
    fixture = Path(__file__).parent / f"migration/fixtures/v4/{fixture_name}.utterplan.json"
    v4_plan = json.loads(fixture.read_text(encoding="utf-8"))
    old_config = v4_plan["config"]
    old_pauses = old_config.get("pauses", {})
    config = PlannerConfig(
        language=old_config["language"],
        document_format=old_config["document_format"],
        unit=old_config.get("unit", "paragraph"),
        text_preparation=old_config.get("text_preparation", "spokenform"),
        pauses=PauseConfig(
            mode=old_pauses.get("mode", "tts"),
            enabled=old_pauses.get("enabled", True),
        ),
    )
    fresh = compile_document(
        v4_plan["source"]["text"],
        input_format=old_config["document_format"],
        config=config,
    ).plan
    migrated = FlowPlan.from_dict(migrate_v4_to_v5(v4_plan))

    assert fresh.plan_id == migrated.plan_id
    assert fresh.flow == migrated.flow
    assert fresh.document == migrated.document
    assert fresh.linguistics == migrated.linguistics
    assert fresh.language == migrated.language
    assert fresh.unit == migrated.unit


def test_fresh_compile_localizes_a_token_cut_by_ssmd_semantics() -> None:
    fixture = Path(__file__).parent / "migration/fixtures/v4/ssmd_09_comprehensive.utterplan.json"
    source = json.loads(fixture.read_text(encoding="utf-8"))["source"]["text"]
    result = compile_document(
        source,
        input_format="ssmd",
        config=PlannerConfig(
            language="sr-Latn",
            document_format="ssmd",
            text_preparation="identity",
        ),
    )

    segments = _segments(result.plan)
    water_segment = next(segment for segment in segments if segment.text == "H2O")
    assert any(segment.text == ", and" for segment in segments)
    assert any(
        token.start == 0 and token.end == 3 and water_segment.text[token.start : token.end] == "H2O"
        for token in water_segment.tokens
    )
    for segment in segments:
        for token in segment.tokens:
            assert segment.text[token.start : token.end]
