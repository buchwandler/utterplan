from __future__ import annotations

import json
from pathlib import Path

import pytest

from utterplan import (
    PlanFormatError,
    PlannerConfig,
    PlanValidationError,
    UnsupportedSchemaError,
    UtterancePlan,
    UtterancePlanner,
)
from utterplan.format import schema, validate_data, validate_file, validate_toml
from utterplan.serialization import from_dict, from_toml, to_dict, to_toml


def plan() -> UtterancePlan:
    return UtterancePlanner(PlannerConfig(language="en-us")).plan("Doctor Smith bought 5 kg.")


def test_public_toml_roundtrip_and_file_apis(tmp_path: Path) -> None:
    original = plan()
    text = original.to_toml()

    assert UtterancePlan.from_dict(original.to_dict()) == original
    assert UtterancePlan.from_toml(text) == original
    assert from_toml(text) == original
    assert to_dict(original) == original.to_dict()
    assert from_dict(original.to_dict()) == original
    assert to_toml(original) == text
    assert validate_data(original.to_dict()) == original
    assert validate_toml(text) == original

    path = tmp_path / "nested" / "plan.utterplan.toml"
    original.save(path)
    assert UtterancePlan.load(path) == original
    assert validate_file(path) == original
    assert path.read_text(encoding="utf-8").startswith('format = "utterplan"')


def test_schema_describes_semantic_data_and_determinism() -> None:
    import jsonschema

    value = plan().to_dict()
    jsonschema.validate(value, schema())
    assert plan().to_toml() == plan().to_toml()


def test_unsupported_schema() -> None:
    value = plan().to_dict()
    value["schema_version"] = 5
    with pytest.raises(UnsupportedSchemaError):
        UtterancePlan.from_dict(value)


def test_semantic_corruption_is_rejected() -> None:
    value = plan().to_dict()
    value["segments"][0]["text"] = "wrong"
    with pytest.raises(PlanValidationError):
        UtterancePlan.from_dict(value)


def test_token_text_must_match_spoken_slice() -> None:
    value = plan().to_dict()
    value["tokens"][0]["text"] = "wrong"
    with pytest.raises(PlanValidationError, match="token.range_mismatch"):
        UtterancePlan.from_dict(value)


def test_compact_optional_fields_are_omitted_from_semantic_values() -> None:
    value = plan().to_dict()
    assert value["segments"]
    assert all(item["structural_start"] is not None for item in value["segments"])
    assert all(item["structural_end"] is not None for item in value["segments"])
    assert all(item["directives"] == {} for item in value["segments"])
    assert all("pos" not in item for item in value["tokens"])
    assert all("tag" not in item for item in value["tokens"])
    assert all(item["morph"] is None for item in value["tokens"])


def test_toml_output_is_plain_engine_independent_plan_data() -> None:
    value = plan().to_toml()
    assert "phonemes" not in value
    assert "numpy" not in value
    assert "schema_version = 4" in value


def test_zero_width_media_roundtrip_validates_semantic_schema() -> None:
    import jsonschema

    result = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
            text_preparation="identity",
        )
    ).plan('[]{src="sfx:impact.knock?seed=42"}')

    payload = result.to_dict()
    jsonschema.validate(payload, schema())
    assert payload["schema_version"] == 4
    assert UtterancePlan.from_toml(result.to_toml()) == result


@pytest.mark.parametrize("name", ["old.utterplan.json", "old.json"])
def test_normal_loading_rejects_json_plan_files(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_text(json.dumps({"format": "utterplan"}), encoding="utf-8")
    with pytest.raises(PlanFormatError, match="JSON is not a supported plan-file format") as error:
        UtterancePlan.load(path)
    assert error.value.code == "format.unsupported_json"
