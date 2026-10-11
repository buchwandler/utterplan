"""Version-aware router for the canonical current TOML plan format."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.exceptions import ParseError

from .codecs import v4_toml
from .codecs.v5_toml import from_v5_toml_data
from .codecs.v6_toml import dumps_v6_toml, from_v6_toml_data, to_v6_toml_data
from .exceptions import PlanFormatError, UnsupportedSchemaError
from .migration import migrate_plan_data
from .model import FlowPlan, UtterancePlan
from .versioning import CURRENT_SCHEMA_VERSION, V4_SCHEMA_VERSION, V5_SCHEMA_VERSION


def _plain(value: Any) -> Any:
    if hasattr(value, "unwrap"):
        value = value.unwrap()
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _current_flow_plan(plan: UtterancePlan | FlowPlan) -> FlowPlan:
    if isinstance(plan, FlowPlan):
        if plan.schema_version == CURRENT_SCHEMA_VERSION:
            return plan
        return FlowPlan.from_dict(migrate_plan_data(plan.to_dict()).data)
    if not isinstance(plan, UtterancePlan):
        raise PlanFormatError("unsupported plan object for TOML serialization", code="plan.type")
    from .migrations.v4_to_v5 import migrate_v4_to_v5

    v5_data = migrate_v4_to_v5(plan.to_dict())
    migrated = migrate_plan_data(v5_data)
    return FlowPlan.from_dict(migrated.data)


def to_toml_data(plan: UtterancePlan | FlowPlan) -> dict[str, Any]:
    """Project any supported model to the current schema-v6 TOML wire format."""
    return to_v6_toml_data(_current_flow_plan(plan))


def from_toml_data(data: Mapping[str, object]) -> FlowPlan:
    """Decode v6 TOML or sequentially migrate frozen v4/v5 TOML into the current model."""
    plain = _plain(data)
    if not isinstance(plain, Mapping):
        raise PlanFormatError("TOML root must be a table", code="toml.root")
    version = plain.get("schema_version")
    if type(version) is not int:
        raise UnsupportedSchemaError(version)
    if version == CURRENT_SCHEMA_VERSION:
        current_plan = from_v6_toml_data(plain)
        current_plan.validate()
        return current_plan
    if version == V5_SCHEMA_VERSION:
        legacy_v5 = from_v5_toml_data(plain)
        migrated_v5 = migrate_plan_data(legacy_v5.to_dict())
        current_plan = FlowPlan.from_dict(migrated_v5.data)
        current_plan.validate()
        return current_plan
    if version == V4_SCHEMA_VERSION:
        from .migrations.v4_to_v5 import migrate_v4_to_v5

        legacy_v4 = v4_toml.decode_v4_toml_data(plain)
        migrated_v4 = migrate_plan_data(migrate_v4_to_v5(legacy_v4))
        current_plan = FlowPlan.from_dict(migrated_v4.data)
        current_plan.validate()
        return current_plan
    raise UnsupportedSchemaError(version)


def dumps_toml(plan: UtterancePlan | FlowPlan) -> str:
    """Serialize the current schema-v6 plan representation to TOML."""
    return dumps_v6_toml(_current_flow_plan(plan))


def loads_toml(value: object) -> FlowPlan:
    """Parse supported TOML and return a validated schema-v6 FlowPlan."""
    if not isinstance(value, str):
        raise PlanFormatError("TOML input must be text", code="toml.type")
    try:
        parsed = tomlkit.parse(value)
    except ParseError as exc:
        line = getattr(exc, "line", None)
        column = getattr(exc, "col", None)
        location = f"line {line}, column {column}: " if line is not None else ""
        raise PlanFormatError(f"{location}{exc}", code="toml.invalid") from exc
    return from_toml_data(parsed.unwrap())


def dump(plan: UtterancePlan | FlowPlan, path: str | Path) -> None:
    """Atomically write a current schema-v6 TOML plan."""
    from .atomic_io import atomic_write_text

    atomic_write_text(path, dumps_toml(plan), create_parent=True)


def load(path: str | Path) -> FlowPlan:
    """Read and decode a schema-v6 or sequentially migratable schema-v4/v5 TOML plan."""
    return loads_toml(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "dump",
    "dumps_toml",
    "from_toml_data",
    "load",
    "loads_toml",
    "to_toml_data",
]
