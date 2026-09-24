from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ..exceptions import PlanMigrationError
from ..hashing import semantic_hash
from .registry import register_migration


def migrate_v2_to_v3(data: Mapping[str, Any]) -> Mapping[str, Any]:
    if data.get("schema_version") != 2:
        raise PlanMigrationError(
            "v2_to_v3 requires schema version 2",
            code="migration.source-version-invalid",
            path="$.schema_version",
        )

    result = deepcopy(dict(data))
    result["schema_version"] = 3
    semantic = deepcopy(result)
    for key in ("plan_id", "producer", "diagnostics", "warnings"):
        semantic.pop(key, None)
    config = semantic.get("config")
    if isinstance(config, Mapping):
        semantic["config"] = dict(config)
        semantic["config"].pop("diagnostics", None)
    result["plan_id"] = semantic_hash(semantic)
    return result


register_migration(2, migrate_v2_to_v3)

__all__ = ["migrate_v2_to_v3"]
