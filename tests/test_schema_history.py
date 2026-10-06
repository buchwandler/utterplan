from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from utterplan import PlanValidationError, UtterancePlan, migrate_plan_data
from utterplan.format import schema

ROOT = Path(__file__).resolve().parent
FIXTURES = sorted((ROOT / "schema_history" / "v1").glob("*.json"))
V2_FIXTURES = sorted((ROOT / "schema_history" / "v2").glob("*.json"))
V3_FIXTURES = sorted((ROOT / "schema_history" / "v3").glob("*.json"))


def test_v1_fixtures_are_present() -> None:
    assert len(FIXTURES) >= 5


def test_v1_fixtures_validate_before_migration_and_remain_immutable() -> None:
    frozen_schema = schema(1)
    current_schema = schema(4)
    for path in FIXTURES:
        value = json.loads(path.read_text(encoding="utf-8"))
        before = copy.deepcopy(value)
        assert value["format"] == "utterplan"
        assert value["schema_version"] == 1
        jsonschema.validate(value, frozen_schema)
        result = migrate_plan_data(value)
        jsonschema.validate(result.data, current_schema)
        assert result.source_version == 1
        assert result.target_version == 4
        assert [(step.source_version, step.target_version) for step in result.steps] == [
            (1, 2),
            (2, 3),
            (3, 4),
        ]
        assert result.data["producer"]["migration"]["original_plan_id"] == value["plan_id"]
        assert all(run["provider"] == "unknown" for run in result.data["linguistic_runs"])
        assert all(token["morph"] is None for token in result.data["tokens"])
        assert all(
            unit["content_hash_schema"] == "utterplan-unit-v3" for unit in result.data["units"]
        )
        if path.name == "multilingual.json":
            with pytest.raises(PlanValidationError) as error:
                UtterancePlan.from_dict(value)
            assert error.value.code == "segment.not_renderable"
            with pytest.raises(PlanValidationError, match="segment.not_renderable"):
                UtterancePlan.from_dict(result.data)
        else:
            plan = UtterancePlan.from_dict(value)
            assert plan.schema_version == 4
            assert plan.plan_id == result.data["plan_id"]
        assert value == before


def test_v2_fixtures_validate_before_migration_and_remain_immutable() -> None:
    assert V2_FIXTURES
    frozen_schema = schema(2)
    current_schema = schema(4)
    for path in V2_FIXTURES:
        value = json.loads(path.read_text(encoding="utf-8"))
        before = copy.deepcopy(value)
        jsonschema.validate(value, frozen_schema)
        result = migrate_plan_data(value)
        assert result.data == migrate_plan_data(value).data
        jsonschema.validate(result.data, current_schema)
        assert result.source_version == 2
        assert result.target_version == 4
        assert [(step.source_version, step.target_version) for step in result.steps] == [
            (2, 3),
            (3, 4),
        ]
        assert result.data["segments"] == value["segments"]
        assert all(
            unit["content_hash_schema"] == "utterplan-unit-v3" for unit in result.data["units"]
        )
        assert [unit["id"] for unit in result.data["units"]] == [
            unit["id"] for unit in value["units"]
        ]
        plan = UtterancePlan.from_dict(value)
        assert plan.schema_version == 4
        assert plan.plan_id == result.data["plan_id"]
        assert value == before


def test_v3_fixtures_are_present() -> None:
    assert {path.name for path in V3_FIXTURES} == {
        "multilingual.json",
        "ssmd_09_comprehensive.json",
    }


def test_v3_fixtures_validate_and_migrate_immutably() -> None:
    frozen_schema = schema(3)
    for path in V3_FIXTURES:
        value = json.loads(path.read_text(encoding="utf-8"))
        before = copy.deepcopy(value)
        assert value["format"] == "utterplan"
        assert value["schema_version"] == 3
        jsonschema.validate(value, frozen_schema)
        migrated = migrate_plan_data(value)
        plan = UtterancePlan.from_dict(value)
        assert plan.schema_version == 4
        assert plan.to_dict() == migrated.data
        assert value == before


def test_every_supported_schema_has_a_registry_entry() -> None:
    from utterplan.schema_registry import has_schema
    from utterplan.versioning import SUPPORTED_SCHEMA_VERSIONS

    assert all(has_schema(version) for version in SUPPORTED_SCHEMA_VERSIONS)
