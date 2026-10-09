from __future__ import annotations

from pathlib import Path

from utterplan import FlowPlan, PauseIntent, PlannerConfig, UtterancePlanner

ROOT = Path(__file__).resolve().parent
HISTORICAL_TOML = sorted(
    path
    for path in (ROOT / "golden").glob("*.utterplan.toml")
    if path.name != "ssmd_09_comprehensive.utterplan.toml"
)
COMPREHENSIVE_SOURCE = ROOT / "fixtures" / "ssmd_09_comprehensive.ssmd"


def test_historical_toml_goldens_migrate_to_current_v5_and_round_trip() -> None:
    assert HISTORICAL_TOML
    for path in HISTORICAL_TOML:
        plan = FlowPlan.load(path)
        assert plan.schema_version == 5
        assert FlowPlan.from_toml(plan.to_toml()) == plan
        assert FlowPlan.from_dict(plan.to_dict()) == plan


def test_canonical_ssmd_09_compiles_to_deterministic_v5_flow() -> None:
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
    assert plan.schema_version == 5
    assert plan.plan_id == "sha256:ebb8ca70464ab7534d74f0fcf2d79af2c02d5498b73de6f21d7a62d6c7d32e46"
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
    assert not {"source", "texts", "annotations", "semantic_boundaries"}.intersection(
        plan.to_dict()
    )
    assert FlowPlan.from_toml(plan.to_toml()) == plan
