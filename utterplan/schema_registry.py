from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from .versioning import CURRENT_SCHEMA_VERSION, SUPPORTED_SCHEMA_VERSIONS

_SCHEMA_RESOURCES: dict[int, str] = {
    1: "schemas/v1.schema.json",
    2: "schemas/v2.schema.json",
    3: "schemas/v3.schema.json",
}


def schema_versions() -> tuple[int, ...]:
    return tuple(sorted(_SCHEMA_RESOURCES))


def has_schema(version: int) -> bool:
    return version in _SCHEMA_RESOURCES


def schema(version: int | None = None) -> dict[str, Any]:
    selected = CURRENT_SCHEMA_VERSION if version is None else version
    if selected not in SUPPORTED_SCHEMA_VERSIONS or selected not in _SCHEMA_RESOURCES:
        raise ValueError(f"unknown UtterPlan schema version: {selected}")
    resource = files("utterplan").joinpath(_SCHEMA_RESOURCES[selected])
    return json.loads(resource.read_text(encoding="utf-8"))


__all__ = ["has_schema", "schema", "schema_versions"]
