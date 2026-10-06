from __future__ import annotations

import datetime
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from utterplan import PlannerConfig, UtterancePlan, UtterancePlanner
from utterplan.exceptions import PlanFormatError, UnsupportedSchemaError
from utterplan.toml_codec import (
    dumps_toml,
    from_toml_data,
    loads_toml,
    to_toml_data,
)
from utterplan.units import make_units

ROOT = Path(__file__).resolve().parent
GOLDENS = sorted((ROOT / "golden").glob("*.utterplan.toml"))


def _plan(path: Path) -> UtterancePlan:
    return UtterancePlan.load(path)


def test_v4_golden_plans_roundtrip_with_semantic_identity_and_determinism() -> None:
    assert GOLDENS
    for path in GOLDENS:
        plan = _plan(path)
        text = dumps_toml(plan)
        restored = loads_toml(text)
        assert dumps_toml(plan) == text
        assert restored.to_dict() == plan.to_dict()
        assert restored.semantic_dict() == plan.semantic_dict()
        assert restored.plan_id == plan.plan_id
        assert [unit.content_hash for unit in restored.units] == [
            unit.content_hash for unit in plan.units
        ]


def test_toml_projection_nests_segments_and_emits_tokens_inline() -> None:
    plan = _plan(ROOT / "golden" / "ssmd_09_comprehensive.utterplan.toml")
    wire = to_toml_data(plan)
    text = dumps_toml(plan)

    assert wire["unit"][0]["segment"][0]["id"] == plan.segments[0].id
    assert "segment_ids" not in wire["unit"][0]
    assert wire["token_stream"]["items"][0]["span"] == [
        plan.tokens[0].spoken_start,
        plan.tokens[0].spoken_end,
    ]
    assert "[[unit.segment]]" in text
    assert "[[token_stream.items]]" not in text
    assert '{id = "token-0", span = [' in text


def test_known_nullable_fields_are_omitted_and_rehydrated() -> None:
    plan = _plan(ROOT / "golden" / "ssmd_09_comprehensive.utterplan.toml")
    wire = to_toml_data(plan)

    assert "version" not in wire["preparation"]
    assert "use_spacy" not in wire["config"]["linguistics"]
    assert "pause_overrides" not in wire["config"]["ssmd"]
    assert "model" not in wire["linguistic_run"][0]
    assert "morph" not in wire["token_stream"]["items"][0]
    assert all("language_run_id" not in item for item in wire["semantic_boundary"])
    assert "strength" not in wire["boundary"][0]

    restored = from_toml_data(wire)
    assert restored.preparation.version is None
    assert restored.config["linguistics"]["use_spacy"] is None
    assert restored.config["ssmd"]["pause_overrides"] is None
    assert restored.linguistic_runs[0].model is None
    assert restored.tokens[0].morph is None
    assert restored.semantic_boundaries[0].language_run_id is None
    assert restored.boundaries[0].strength is None


def test_arbitrary_nested_metadata_null_roundtrips_through_reserved_sentinel() -> None:
    original = _plan(ROOT / "golden" / "basic_en.utterplan.toml")
    plan = replace(
        original,
        document_metadata={"nested": {"missing": None, "items": [1, None, "x"]}},
    ).with_identity()
    wire = to_toml_data(plan)

    assert wire["document_metadata"]["nested"]["missing"] == {"__utterplan_null__": True}
    restored = from_toml_data(wire)
    assert restored.document_metadata == plan.document_metadata
    assert restored.plan_id == plan.plan_id


def test_reserved_metadata_keys_are_rejected_when_encoding_or_decoding() -> None:
    plan = _plan(ROOT / "golden" / "basic_en.utterplan.toml")
    conflicted = replace(plan, document_metadata={"__utterplan_custom__": "value"})
    with pytest.raises(PlanFormatError, match="reserved metadata key"):
        to_toml_data(conflicted)

    wire = to_toml_data(plan)
    wire["document_metadata"] = {"custom": {"__utterplan_null__": False}}
    with pytest.raises(PlanFormatError, match="conflicting reserved metadata sentinel"):
        from_toml_data(wire)


def test_toml_preserves_unicode_and_pathological_text_exactly() -> None:
    empty = UtterancePlanner(PlannerConfig(language="en-us", text_preparation="identity")).plan("")
    values = [
        "Unicode café € 🙂 ∑",
        'quotes " and triple quotes """ stay exact',
        "backslash \\\\ followed by newline\n",
        "\nleading and trailing\n",
        "",
    ]
    for value in values:
        plan = replace(
            empty,
            source=replace(empty.source, text=value),
            texts=replace(empty.texts, structural=value, spoken=value),
        ).with_identity()
        restored = loads_toml(dumps_toml(plan))
        assert restored.source.text == value
        assert restored.texts.structural == value
        assert restored.texts.spoken == value
        assert restored.plan_id == plan.plan_id


def test_spacy_morph_field_survives_projection_and_roundtrip() -> None:
    plan = _plan(ROOT / "golden" / "ssmd_09_comprehensive.utterplan.toml")
    tokens = list(plan.tokens)
    tokens[0] = replace(tokens[0], morph="NumType=Card")
    units = make_units(
        plan.segments,
        plan.markers,
        tuple(tokens),
        plan.units[0].kind,
        plan.semantic_boundaries,
    )
    plan = replace(plan, tokens=tuple(tokens), units=units, plan_id="").with_identity()

    restored = loads_toml(dumps_toml(plan))
    assert restored.tokens[0].morph == "NumType=Card"
    assert restored.to_dict() == plan.to_dict()


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (datetime.date(2025, 1, 1), "date/time"),
        (float("nan"), "non-finite"),
        (float("inf"), "non-finite"),
    ],
)
def test_metadata_rejects_datetime_and_nonfinite_floats(value: object, message: str) -> None:
    plan = _plan(ROOT / "golden" / "basic_en.utterplan.toml")
    wire = to_toml_data(plan)
    wire["document_metadata"]["invalid"] = value
    with pytest.raises(PlanFormatError, match=message):
        from_toml_data(wire)


def test_invalid_toml_reports_location() -> None:
    with pytest.raises(PlanFormatError, match=r"line 2, column") as error:
        loads_toml('format = "utterplan"\nschema_version = [\n')
    assert error.value.code == "toml.invalid"


def test_unknown_root_fields_and_future_schema_are_rejected() -> None:
    plan = _plan(ROOT / "golden" / "basic_en.utterplan.toml")
    wire: dict[str, Any] = to_toml_data(plan)
    wire["extra"] = True
    with pytest.raises(PlanFormatError, match="unknown top-level TOML fields"):
        from_toml_data(wire)

    wire = to_toml_data(plan)
    wire["schema_version"] = 5
    with pytest.raises(UnsupportedSchemaError):
        from_toml_data(wire)
