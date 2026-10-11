from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import tomlkit

from ..exceptions import PlanFormatError
from ..hashing import FLOW_HASH_SCHEMA, V5_FLOW_HASH_SCHEMA
from ..model import FlowPlan
from .v5_toml import dumps_v5_toml, from_v5_toml_data, to_v5_toml_data


def _plain(value: Any) -> Any:
    if hasattr(value, "unwrap"):
        value = value.unwrap()
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _v5_plan_view(plan: FlowPlan) -> FlowPlan:
    return FlowPlan(
        language=plan.language,
        unit=plan.unit,
        flow=plan.flow,
        document=plan.document,
        linguistics=plan.linguistics,
        producer=plan.producer,
        warnings=plan.warnings,
        format=plan.format,
        schema_version=5,
        hash_schema=V5_FLOW_HASH_SCHEMA,
    )


def to_v6_toml_data(plan: FlowPlan) -> dict[str, Any]:
    if not isinstance(plan, FlowPlan) or plan.schema_version != 6:
        raise PlanFormatError(
            "v6 TOML serialization requires a schema-v6 FlowPlan", code="plan.type"
        )
    result = to_v5_toml_data(_v5_plan_view(plan))
    result["schema_version"] = 6
    result["plan_id"] = plan.plan_id
    result["hash_schema"] = FLOW_HASH_SCHEMA
    if plan.source is not None:
        result["source"] = plan.source.to_portable_dict()
    return result


def from_v6_toml_data(data: Mapping[str, Any]) -> FlowPlan:
    plain = _plain(data)
    if not isinstance(plain, Mapping):
        raise PlanFormatError("TOML root must be a table", code="toml.root")
    if plain.get("format") != "utterplan" or plain.get("schema_version") != 6:
        raise PlanFormatError("expected schema-v6 UtterPlan TOML", code="schema.version")
    if plain.get("hash_schema") != FLOW_HASH_SCHEMA:
        raise PlanFormatError("unsupported v6 flow hash schema", code="flow.hash_schema")
    allowed = {
        "format",
        "schema_version",
        "plan_id",
        "language",
        "unit",
        "hash_schema",
        "document",
        "linguistics",
        "flow",
        "producer",
        "warnings",
        "source",
    }
    unknown = set(plain) - allowed
    required = {"format", "schema_version", "plan_id", "language", "unit", "hash_schema", "flow"}
    missing = required - set(plain)
    if missing:
        raise PlanFormatError(
            f"required v6 TOML fields are missing: {sorted(missing)}", code="field.required"
        )
    if unknown:
        raise PlanFormatError(
            f"unknown top-level TOML fields: {sorted(unknown)}", code="field.unknown"
        )

    legacy_wire = dict(plain)
    source = legacy_wire.pop("source", None)
    legacy_wire["schema_version"] = 5
    legacy_wire["hash_schema"] = V5_FLOW_HASH_SCHEMA
    legacy_wire["plan_id"] = ""
    legacy = from_v5_toml_data(legacy_wire)
    semantic = legacy.to_dict()
    semantic["schema_version"] = 6
    semantic["hash_schema"] = FLOW_HASH_SCHEMA
    semantic["plan_id"] = ""
    if source is not None:
        semantic["source"] = source
    plan = FlowPlan.from_dict(semantic)
    if plain.get("plan_id") != plan.plan_id:
        raise PlanFormatError(
            "plan ID does not match v6 executable semantics", code="plan.identity"
        )
    plan.validate()
    return plan


def dumps_v6_toml(plan: FlowPlan) -> str:
    wire = to_v6_toml_data(plan)
    document = tomlkit.parse(dumps_v5_toml(_v5_plan_view(plan)))
    document["schema_version"] = 6
    document["plan_id"] = plan.plan_id
    document["hash_schema"] = FLOW_HASH_SCHEMA
    source = wire.get("source")
    if isinstance(source, Mapping):
        source_table = tomlkit.table()
        for key in ("format", "text", "sha256"):
            source_table[key] = source[key]
        document.add("source", source_table)
    return tomlkit.dumps(document)


__all__ = ["dumps_v6_toml", "from_v6_toml_data", "to_v6_toml_data"]
