"""Public semantic-data and TOML serialization helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .model import FlowPlan, UtterancePlan
from .toml_codec import dumps_toml, loads_toml


def to_dict(plan: UtterancePlan | FlowPlan) -> dict[str, Any]:
    """Return the model's canonical semantic mapping."""
    return plan.to_dict()


def from_dict(data: Mapping[str, Any]) -> FlowPlan:
    """Load a schema-v7 plan without implicitly migrating historical mappings."""
    plan = FlowPlan.from_dict(data)
    plan.validate()
    return plan


def to_toml(plan: UtterancePlan | FlowPlan) -> str:
    """Serialize a plan to its versioned canonical TOML representation."""
    return dumps_toml(plan)


def from_toml(value: str) -> FlowPlan:
    """Deserialize and validate a schema-v7 TOML plan."""
    result = loads_toml(value)
    if not isinstance(result, FlowPlan):
        raise ValueError("TOML did not decode to a current FlowPlan")
    return result


__all__ = ["from_dict", "from_toml", "to_dict", "to_toml"]
