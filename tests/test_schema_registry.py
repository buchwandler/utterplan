from __future__ import annotations

import json
from pathlib import Path

import pytest

from utterplan.format import schema
from utterplan.schema_registry import has_schema, schema_versions
from utterplan.versioning import (
    CURRENT_SCHEMA_VERSION,
    FORMAT,
    JSON_SCHEMA_VERSIONS,
    OLDEST_SUPPORTED_SCHEMA_VERSION,
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
)


def test_schema_registry_separates_supported_plans_from_historical_json_schemas() -> None:
    assert FORMAT == "utterplan"
    assert CURRENT_SCHEMA_VERSION == 5
    assert SCHEMA_VERSION == CURRENT_SCHEMA_VERSION
    assert OLDEST_SUPPORTED_SCHEMA_VERSION == 1
    assert SUPPORTED_SCHEMA_VERSIONS == (1, 2, 3, 4, 5)
    assert JSON_SCHEMA_VERSIONS == (1, 2, 3, 4)
    assert schema_versions() == JSON_SCHEMA_VERSIONS
    assert all(has_schema(version) for version in JSON_SCHEMA_VERSIONS)
    assert not has_schema(5)
    for version in JSON_SCHEMA_VERSIONS:
        assert schema(version)["properties"]["schema_version"]["const"] == version
    with pytest.raises(ValueError, match="no historical JSON schema"):
        schema(5)


def test_default_json_schema_is_the_latest_historical_schema_not_current_v5() -> None:
    assert schema() == schema(4)
    assert CURRENT_SCHEMA_VERSION not in JSON_SCHEMA_VERSIONS


def test_versioned_source_and_packaged_schema_resources_are_identical() -> None:
    root = Path(__file__).resolve().parent.parent
    for version in JSON_SCHEMA_VERSIONS:
        source = json.loads((root / "spec" / "schemas" / f"v{version}.schema.json").read_text())
        packaged = json.loads(
            (root / "utterplan" / "schemas" / f"v{version}.schema.json").read_text()
        )
        assert source == packaged
    assert len(
        {
            json.loads((root / "spec" / "schemas" / f"v{version}.schema.json").read_text())["$id"]
            for version in JSON_SCHEMA_VERSIONS
        }
    ) == len(JSON_SCHEMA_VERSIONS)
