"""Plan validation APIs for semantic data and the TOML wire format."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .model import FlowPlan
from .schema_registry import schema as _schema
from .serialization import from_dict
from .toml_codec import load as load_toml
from .toml_codec import loads_toml
from .versioning import FORMAT, SCHEMA_VERSION

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "v4.schema.json"
PACKAGE_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "v4.schema.json"


def validate_data(value: Any) -> FlowPlan:
    """Validate or migrate a semantic mapping into the current v5 flow model."""
    return from_dict(value)


def validate_toml(value: str) -> FlowPlan:
    """Validate a current v5 or migratable v4 TOML plan."""
    return loads_toml(value)


def validate_file(path: str | Path) -> FlowPlan:
    """Validate a saved v5 or migratable v4 TOML plan file."""
    return load_toml(path)


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
