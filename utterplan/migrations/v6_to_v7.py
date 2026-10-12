from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..exceptions import PlanMigrationError
from .registry import register_migration


def migrate_v6_to_v7(data: Mapping[str, Any]) -> dict[str, Any]:
    """Require source recompilation rather than inventing a partial v7 inventory."""
    if not isinstance(data, Mapping) or data.get("format") != "utterplan":
        raise PlanMigrationError(
            "v6_to_v7 requires an UtterPlan mapping",
            code="migration.source-invalid",
        )
    if data.get("schema_version") != 6:
        raise PlanMigrationError(
            "v6_to_v7 requires schema version 6",
            code="migration.source-version-invalid",
            path="$.schema_version",
        )
    raise PlanMigrationError(
        "schema-v6 plans may have omitted renderer-dependent automatic boundaries. "
        "Recompile the original source with current UtterPlan to create a complete "
        "schema-v7 universal-boundary plan.",
        code="migration.recompile_required",
        path="$.schema_version",
    )


register_migration(6, migrate_v6_to_v7)

__all__ = ["migrate_v6_to_v7"]
