import json

import pytest

from utterplan import (
    PlannerConfig,
    PlanValidationError,
    UnsupportedSchemaError,
    UtterancePlan,
    UtterancePlanner,
)
from utterplan.format import schema


def plan():
    return UtterancePlanner(PlannerConfig(language="en-us")).plan("Doctor Smith bought 5 kg.")


def test_roundtrip_all_apis(tmp_path):
    original = plan()
    assert UtterancePlan.from_dict(original.to_dict()) == original
    assert UtterancePlan.from_json(original.to_json()) == original
    path = tmp_path / "plan.utterplan.json"
    original.save(path)
    assert UtterancePlan.load(path) == original
    assert UtterancePlan.load(path).plan_id == original.plan_id


def test_schema_and_determinism():
    import jsonschema

    value = plan().to_dict()
    jsonschema.validate(value, schema())
    assert plan().to_dict() == plan().to_dict()


def test_unsupported_schema():
    value = plan().to_dict()
    value["schema_version"] = 3
    with pytest.raises(UnsupportedSchemaError):
        UtterancePlan.from_dict(value)


def test_semantic_corruption_is_rejected():
    value = plan().to_dict()
    value["segments"][0]["text"] = "wrong"
    with pytest.raises(PlanValidationError):
        UtterancePlan.from_dict(value)


def test_token_text_must_match_spoken_slice():
    value = plan().to_dict()
    value["tokens"][0]["text"] = "wrong"
    with pytest.raises(PlanValidationError, match="token.range_mismatch"):
        UtterancePlan.from_dict(value)


def test_compact_optional_fields_are_omitted():
    value = plan().to_dict()
    assert value["segments"]
    assert all("structural_start" not in item for item in value["segments"])
    assert all("structural_end" not in item for item in value["segments"])
    assert all(item["directives"] == {} for item in value["segments"])
    assert all("pos" not in item for item in value["tokens"])
    assert all("tag" not in item for item in value["tokens"])

    assert all(item["morph"] is None for item in value["tokens"])


def test_json_is_plain_data():
    value = json.loads(plan().to_json())
    assert "phonemes" not in json.dumps(value)
    assert "numpy" not in json.dumps(value)
