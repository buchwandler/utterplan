from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import jsonschema

from utterplan import PlannerConfig, UtterancePlan, UtterancePlanner
from utterplan.format import schema

ROOT = Path(__file__).resolve().parent
GOLDEN = sorted((ROOT / "golden").glob("*.utterplan.json"))
COMPREHENSIVE_SOURCE = ROOT / "fixtures" / "ssmd_09_comprehensive.ssmd"
COMPREHENSIVE_GOLDEN = ROOT / "golden" / "ssmd_09_comprehensive.utterplan.json"


def test_golden_plans_roundtrip_and_validate() -> None:
    assert GOLDEN
    for path in GOLDEN:
        plan = UtterancePlan.load(path)
        jsonschema.validate(plan.to_dict(), schema())
        assert UtterancePlan.from_json(plan.to_json()) == plan


def test_canonical_ssmd_09_compiles_to_comprehensive_v3_golden() -> None:
    source = COMPREHENSIVE_SOURCE.read_text(encoding="utf-8")
    plan = UtterancePlanner(
        PlannerConfig(language="en-us", document_format="ssmd", text_preparation="identity")
    ).plan(source)
    expected = UtterancePlan.load(COMPREHENSIVE_GOLDEN)
    expected = replace(
        expected,
        producer={**expected.producer, "version": plan.producer["version"]},
    )

    assert plan == expected
    assert plan.schema_version == 3
    assert plan.document_metadata["language"] == "sr-Latn"
    assert any(
        annotation.kind == "lang" and annotation.attrs["lang"] == "sr-Latn"
        for annotation in plan.annotations
    )
    assert plan.document_metadata["header"]["ssmd_version"] == "0.9"
    assert plan.document_metadata["voice_defaults"]["narrator"]["rate"] == "slow"
    assert any(event.kind == "heading" for event in plan.boundaries)
    assert any(event.kind == "paragraph" for event in plan.boundaries)
    assert any(event.kind == "explicit" for event in plan.boundaries)
    assert [marker.name for marker in plan.markers] == ["checkpoint"]

    welcome = next(segment for segment in plan.segments if segment.text.startswith("Welcome"))
    important = next(segment for segment in plan.segments if segment.text == "Important")
    assert welcome.paragraph == important.paragraph
    assert welcome.directives.voice.reference == "narrator"
    assert welcome.directives.voice.name == "Mira"
    assert welcome.directives.prosody.rate == "medium"
    assert important.directives.prosody.rate == "slow"
    inner = next(segment for segment in plan.segments if segment.text.startswith("Inner scope"))
    assert inner.directives.prosody.rate == "fast"
    assert inner.directives.prosody.pitch == "high"
