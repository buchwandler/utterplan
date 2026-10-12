from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ..exceptions import PlanMigrationError
from ..hashing import V5_FLOW_HASH_SCHEMA, V6_FLOW_HASH_SCHEMA, flow_plan_id
from .registry import register_migration


def migrate_v5_to_v6(data: Mapping[str, Any]) -> dict[str, Any]:
    """Upgrade serialized v5 semantics without inventing unavailable original source."""
    if not isinstance(data, Mapping) or data.get("format") != "utterplan":
        raise PlanMigrationError(
            "v5_to_v6 requires an UtterPlan mapping",
            code="migration.source-invalid",
        )
    if data.get("schema_version") != 5:
        raise PlanMigrationError(
            "v5_to_v6 requires schema version 5",
            code="migration.source-version-invalid",
            path="$.schema_version",
        )
    if data.get("hash_schema") != V5_FLOW_HASH_SCHEMA:
        raise PlanMigrationError(
            "v5 plan uses an unsupported flow hash schema",
            code="migration.hash-schema-invalid",
            path="$.hash_schema",
        )
    if "source" in data:
        raise PlanMigrationError(
            "schema-v5 plans cannot contain source provenance",
            code="migration.source-version-invalid",
            path="$.source",
        )

    result = deepcopy(dict(data))
    result["schema_version"] = 6
    result["hash_schema"] = V6_FLOW_HASH_SCHEMA
    result["plan_id"] = ""
    result["plan_id"] = flow_plan_id(result)
    return result


register_migration(5, migrate_v5_to_v6)

__all__ = ["migrate_v5_to_v6"]
