"""Plan validation APIs for semantic data and the TOML wire format."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .model import UtterancePlan
from .schema_registry import schema as _schema
from .toml_codec import loads_toml
from .versioning import FORMAT, SCHEMA_VERSION

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "spec" / "utterplan.schema.json"
PACKAGE_SCHEMA_PATH = Path(__file__).resolve().parent / "utterplan.schema.json"


def validate_data(value: Any) -> UtterancePlan:
    """Validate a canonical semantic mapping (not a plan-file syntax)."""
    return UtterancePlan.from_dict(value)


def validate_toml(value: str) -> UtterancePlan:
    """Validate a TOML UtterancePlan document."""
    return loads_toml(value)


def validate_file(path: str | Path) -> UtterancePlan:
    """Validate a saved TOML plan file."""
    return UtterancePlan.load(path)


def schema(version: int | None = None) -> dict[str, Any]:
    """Return JSON Schema describing the decoded semantic mapping."""
    return _schema(version)


__all__ = [
    "FORMAT",
    "SCHEMA_VERSION",
    "SCHEMA_PATH",
    "PACKAGE_SCHEMA_PATH",
    "validate_data",
    "validate_toml",
    "validate_file",
    "schema",
]
