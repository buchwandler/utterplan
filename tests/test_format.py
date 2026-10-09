from __future__ import annotations

import json
from pathlib import Path

import pytest

from utterplan import FlowPlan, PlannerConfig, UtterancePlanner
from utterplan.exceptions import PlanFormatError, UnsupportedSchemaError
from utterplan.format import (
    PACKAGE_SCHEMA_PATH,
    SCHEMA_PATH,
    schema,
    validate_data,
    validate_file,
    validate_toml,
)


def plan() -> FlowPlan:
    return UtterancePlanner(PlannerConfig(language="en-us")).plan("Doctor Smith bought 5 kg.")


def test_public_v5_toml_roundtrip_and_file_apis(tmp_path: Path) -> None:
    original = plan()
    text = original.to_toml()

    assert FlowPlan.from_dict(original.to_dict()) == original
    assert FlowPlan.from_toml(text) == original
    assert validate_data(original.to_dict()) == original
    assert validate_toml(text) == original

    path = tmp_path / "nested" / "plan.utterplan.toml"
    original.save(path, create_parent=True)
    assert FlowPlan.load(path) == original
    assert validate_file(path) == original
    assert path.read_text(encoding="utf-8").startswith('format = "utterplan"')


def test_current_v5_model_is_not_checked_against_historical_v4_json_schema() -> None:
    value = plan().to_dict()
    assert value["schema_version"] == 5
    assert SCHEMA_PATH.name == "v4.schema.json"
    assert PACKAGE_SCHEMA_PATH == SCHEMA_PATH
    assert schema(4) == json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="no historical JSON schema"):
        schema(5)
    assert validate_data(value).schema_version == 5


def test_future_schema_is_rejected() -> None:
    value = plan().to_dict()
    value["schema_version"] = 6
    with pytest.raises(UnsupportedSchemaError):
        validate_data(value)


def test_semantic_corruption_is_rejected() -> None:
    value = plan().to_dict()
    value["flow"][0]["segments"][0]["text"] = "wrong"
    with pytest.raises(PlanFormatError):
        FlowPlan.from_dict(value)


def test_token_span_must_fit_owning_segment_text() -> None:
    value = plan().to_dict()
    value["flow"][0]["segments"][0]["tokens"][0]["end"] = 999
    with pytest.raises(PlanFormatError):
        FlowPlan.from_dict(value)


def test_toml_output_is_plain_engine_independent_flow_data() -> None:
    text = plan().to_toml()
    assert "phonemes" not in text
    assert "numpy" not in text
    assert "schema_version = 5" in text
    assert "source =" not in text
    assert "token_indices" not in text


def test_zero_width_media_roundtrip_uses_current_flow_contract() -> None:
    result = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
            text_preparation="identity",
        )
    ).plan('[]{src="sfx:impact.knock?seed=42"}')

    payload = result.to_dict()
    assert payload["schema_version"] == 5
    restored = FlowPlan.from_toml(result.to_toml())
    media = [
        segment
        for unit in restored.flow
        for segment in unit.segments
        if segment.directives.audio is not None
    ]
    assert len(media) == 1
    assert media[0].text == ""
    assert media[0].directives.audio.src == "sfx:impact.knock?seed=42"


@pytest.mark.parametrize("name", ["old.utterplan.json", "old.json"])
def test_normal_loading_rejects_json_plan_files(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_text(json.dumps({"format": "utterplan"}), encoding="utf-8")
    with pytest.raises(PlanFormatError, match="JSON is not a supported plan-file format") as error:
        FlowPlan.load(path)
    assert error.value.code == "format.unsupported_json"
