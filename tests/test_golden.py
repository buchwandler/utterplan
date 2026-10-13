from __future__ import annotations

from pathlib import Path

import pytest

from utterplan import FlowPlan, PauseIntent, PlannerConfig, UtterancePlanner
from utterplan.exceptions import UnsupportedSchemaError

ROOT = Path(__file__).resolve().parent
HISTORICAL_TOML = sorted(
    path
    for path in (ROOT / "golden").glob("*.utterplan.toml")
    if path.name != "ssmd_09_comprehensive.utterplan.toml"
)
COMPREHENSIVE_SOURCE = ROOT / "fixtures" / "ssmd_09_comprehensive.ssmd"


def test_historical_toml_goldens_are_rejected_by_normal_loaders() -> None:
    assert HISTORICAL_TOML
    for path in HISTORICAL_TOML:
        with pytest.raises(UnsupportedSchemaError) as error:
            FlowPlan.load(path)
        assert error.value.code == "schema.version_unsupported"


def test_canonical_ssmd_09_compiles_to_deterministic_v7_flow() -> None:
    source = COMPREHENSIVE_SOURCE.read_text(encoding="utf-8")
    config = PlannerConfig(
        language="en-us",
        document_format="ssmd",
        text_preparation="identity",
        renderability_mode="strict",
    )
    planner = UtterancePlanner(config)
    plan = planner.plan(source)
    repeated = planner.plan(source)

    assert plan == repeated
    assert plan.schema_version == 7
    assert plan.plan_id == "sha256:e69c94cb70f67c51d94428d5a00563d2eed9cba03d1687366eaabe654df03df1"
    assert plan.document.format == "ssmd"
    assert plan.document.ssmd_version == "0.9"
    assert plan.document.title == "Renderer-neutral SSMD 0.9 contract"
    assert plan.document.semantics["voice_bindings"]["narrator"] == "provider-voice"
    assert len(plan.flow) == 7

    segments = [segment for unit in plan.flow for segment in unit.segments]
    welcome = next(segment for segment in segments if segment.text == "Welcome")
    important = next(segment for segment in segments if segment.text == "Important")
    inner = next(segment for segment in segments if segment.text.startswith("Inner scope"))
    assert welcome.language == "sr-Latn"
    assert welcome.directives.voice is not None
    assert welcome.directives.voice.name == "Mira"
    assert welcome.directives.prosody is not None
    assert welcome.directives.prosody.rate == "medium"
    assert important.directives.emphasis is not None
    assert important.directives.say_as is None
    assert inner.directives.prosody is not None
    assert inner.directives.prosody.rate == "fast"
    assert inner.directives.prosody.pitch == "high"
    assert any(segment.pause_after == PauseIntent("timed", "500ms") for segment in segments)
    assert any(segment.heading == 2 and "checkpoint" in segment.markers for segment in segments)
    assert {"texts", "annotations", "semantic_boundaries"}.isdisjoint(plan.to_dict())
    assert plan.source is not None and plan.source.text == source
    assert FlowPlan.from_toml(plan.to_toml()) == plan
