from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from .versioning import JSON_SCHEMA_VERSIONS

_SCHEMA_RESOURCES: dict[int, str] = {
    1: "schemas/v1.schema.json",
    2: "schemas/v2.schema.json",
    3: "schemas/v3.schema.json",
    4: "schemas/v4.schema.json",
}


def schema_versions() -> tuple[int, ...]:
    """Return versions with historical JSON Schema resources (not all supported plans)."""
    return JSON_SCHEMA_VERSIONS


def has_schema(version: int) -> bool:
    return version in _SCHEMA_RESOURCES


def schema(version: int | None = None) -> dict[str, Any]:
    """Load a historical JSON schema; v5 is validated by its TOML/model contract."""
    selected = max(JSON_SCHEMA_VERSIONS) if version is None else version
    if selected not in _SCHEMA_RESOURCES:
        raise ValueError(f"no historical JSON schema for UtterPlan version: {selected}")
    resource = files("utterplan").joinpath(_SCHEMA_RESOURCES[selected])
    return json.loads(resource.read_text(encoding="utf-8"))


__all__ = ["has_schema", "schema", "schema_versions"]
