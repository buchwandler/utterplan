"""Public semantic-data and TOML serialization helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .model import UtterancePlan
from .toml_codec import dumps_toml, loads_toml


def to_dict(plan: UtterancePlan) -> dict[str, Any]:
    """Return the canonical semantic mapping."""
    return plan.to_dict()


def from_dict(data: Mapping[str, Any]) -> UtterancePlan:
    """Construct a validated plan from the canonical semantic mapping."""
    return UtterancePlan.from_dict(data)


def to_toml(plan: UtterancePlan) -> str:
    """Serialize a plan to the canonical TOML wire format."""
    return dumps_toml(plan)


def from_toml(value: str) -> UtterancePlan:
    """Deserialize a plan from the canonical TOML wire format."""
    return loads_toml(value)


__all__ = ["from_dict", "from_toml", "to_dict", "to_toml"]
