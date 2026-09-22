from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema

from utterplan import UtterancePlan, migrate_plan_data
from utterplan.format import schema

ROOT = Path(__file__).resolve().parent
FIXTURES = sorted((ROOT / "schema_history" / "v1").glob("*.json"))


def test_v1_fixtures_are_present() -> None:
    assert len(FIXTURES) >= 5


def test_v1_fixtures_validate_before_migration_and_remain_immutable() -> None:
    frozen_schema = schema(1)
    current_schema = schema(2)
    for path in FIXTURES:
        value = json.loads(path.read_text(encoding="utf-8"))
        before = copy.deepcopy(value)
        assert value["format"] == "utterplan"
        assert value["schema_version"] == 1
        jsonschema.validate(value, frozen_schema)
        result = migrate_plan_data(value)
        jsonschema.validate(result.data, current_schema)
        assert result.source_version == 1
        assert result.target_version == 2
        assert result.data["producer"]["migration"]["original_plan_id"] == value["plan_id"]
        assert all(run["provider"] == "unknown" for run in result.data["linguistic_runs"])
        assert all(token["morph"] is None for token in result.data["tokens"])
        assert all(unit["content_hash_schema"] == "utterplan-unit-v2" for unit in result.data["units"])
        plan = UtterancePlan.from_dict(value)
        assert plan.schema_version == 2
        assert plan.plan_id == result.data["plan_id"]
        assert value == before


def test_every_supported_schema_has_a_registry_entry() -> None:
    from utterplan.schema_registry import has_schema
    from utterplan.versioning import SUPPORTED_SCHEMA_VERSIONS

    assert all(has_schema(version) for version in SUPPORTED_SCHEMA_VERSIONS)
