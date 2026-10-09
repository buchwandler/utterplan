"""Public semantic-data and TOML serialization helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .migration import migrate_plan_data
from .model import FlowPlan, UtterancePlan
from .toml_codec import dumps_toml, loads_toml
from .versioning import CURRENT_SCHEMA_VERSION


def to_dict(plan: UtterancePlan | FlowPlan) -> dict[str, Any]:
    """Return the model's canonical semantic mapping."""
    return plan.to_dict()


def from_dict(data: Mapping[str, Any]) -> FlowPlan:
    """Load current v5 semantics, migrating supported historical JSON mappings."""
    if data.get("schema_version") == CURRENT_SCHEMA_VERSION:
        return FlowPlan.from_dict(data)
    migrated = migrate_plan_data(data)
    return FlowPlan.from_dict(migrated.data)


def to_toml(plan: UtterancePlan | FlowPlan) -> str:
    """Serialize a plan to its versioned canonical TOML representation."""
    return dumps_toml(plan)


def from_toml(value: str) -> FlowPlan:
    """Deserialize and migrate a supported TOML plan to the current v5 model."""
    result = loads_toml(value)
    if not isinstance(result, FlowPlan):
        raise ValueError("TOML did not decode to a current v5 FlowPlan")
    return result


__all__ = ["from_dict", "from_toml", "to_dict", "to_toml"]
