from __future__ import annotations

import json
from pathlib import Path

from utterplan.format import schema
from utterplan.schema_registry import has_schema, schema_versions
from utterplan.versioning import (
    CURRENT_SCHEMA_VERSION,
    FORMAT,
    OLDEST_SUPPORTED_SCHEMA_VERSION,
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
)


def test_schema_registry_lists_frozen_v1_v3_and_current_v4() -> None:
    assert FORMAT == "utterplan"
    assert CURRENT_SCHEMA_VERSION == 4
    assert SCHEMA_VERSION == CURRENT_SCHEMA_VERSION
    assert OLDEST_SUPPORTED_SCHEMA_VERSION == 1
    assert SUPPORTED_SCHEMA_VERSIONS == (1, 2, 3, 4)
    assert schema_versions() == (1, 2, 3, 4)
    assert has_schema(1)
    assert has_schema(2)
    assert has_schema(3)
    assert has_schema(4)
    assert schema(1)["properties"]["schema_version"]["const"] == 1
    assert schema(2)["properties"]["schema_version"]["const"] == 2
    assert schema(3)["properties"]["schema_version"]["const"] == 3
    assert schema(4)["properties"]["schema_version"]["const"] == 4


def test_current_schema_alias_matches_current_version() -> None:
    assert schema() == schema(CURRENT_SCHEMA_VERSION)


def test_source_and_packaged_schema_resources_are_identical() -> None:
    root = Path(__file__).resolve().parent.parent
    source_v1 = json.loads((root / "spec" / "schemas" / "v1.schema.json").read_text())
    packaged_v1 = json.loads((root / "utterplan" / "schemas" / "v1.schema.json").read_text())
    source_v2 = json.loads((root / "spec" / "schemas" / "v2.schema.json").read_text())
    packaged_v2 = json.loads((root / "utterplan" / "schemas" / "v2.schema.json").read_text())
    source_v3 = json.loads((root / "spec" / "schemas" / "v3.schema.json").read_text())
    packaged_v3 = json.loads((root / "utterplan" / "schemas" / "v3.schema.json").read_text())
    source_v4 = json.loads((root / "spec" / "schemas" / "v4.schema.json").read_text())
    packaged_v4 = json.loads((root / "utterplan" / "schemas" / "v4.schema.json").read_text())
    current_source = json.loads((root / "spec" / "utterplan.schema.json").read_text())
    current_packaged = json.loads((root / "utterplan" / "utterplan.schema.json").read_text())
    assert source_v1 == packaged_v1
    assert source_v2 == packaged_v2
    assert source_v3 == packaged_v3
    assert source_v4 == packaged_v4 == current_source == current_packaged
    assert source_v1 != source_v2 != source_v3 != source_v4
