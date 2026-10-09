"""Deterministic serialization for optional compiler provenance sidecars."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import tomlkit
from tomlkit.exceptions import ParseError

from .compiler import PreparationChange, PreparationTrace, PreparationTraceUnit
from .exceptions import PlanFormatError
from .model import Diagnostic

_TRACE_FORMAT = "utterplan.trace"
_TRACE_SCHEMA_VERSION = 1


def dumps_trace(trace: PreparationTrace) -> str:
    """Serialize a full trace in a TOML envelope with lossless JSON payload data."""
    document = tomlkit.document()
    document["format"] = _TRACE_FORMAT
    document["schema_version"] = _TRACE_SCHEMA_VERSION
    document["source_sha256"] = trace.source_sha256
    document["payload_json"] = json.dumps(
        trace.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return tomlkit.dumps(document)


def loads_trace(value: object) -> PreparationTrace:
    """Decode and validate one compiler-trace TOML sidecar."""
    if not isinstance(value, str):
        raise PlanFormatError("trace input must be TOML text", code="toml.type")
    try:
        root = tomlkit.parse(value).unwrap()
    except ParseError as exc:
        line = getattr(exc, "line", None)
        column = getattr(exc, "col", None)
        location = f"line {line}, column {column}: " if line is not None else ""
        raise PlanFormatError(f"{location}{exc}", code="toml.invalid") from exc
    if not isinstance(root, Mapping):
        raise PlanFormatError("trace root must be a TOML table", code="trace.root")
    if set(root) != {"format", "schema_version", "source_sha256", "payload_json"}:
        raise PlanFormatError("trace envelope fields are invalid", code="trace.fields")
    if root.get("format") != _TRACE_FORMAT or root.get("schema_version") != _TRACE_SCHEMA_VERSION:
        raise PlanFormatError("unsupported trace schema", code="trace.schema")
    payload_json = root.get("payload_json")
    if not isinstance(payload_json, str):
        raise PlanFormatError("trace payload_json must be text", code="trace.payload")
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        raise PlanFormatError(str(exc), code="trace.payload") from exc
    if not isinstance(payload, Mapping):
        raise PlanFormatError("trace payload must be an object", code="trace.payload")
    trace = _trace_from_dict(payload)
    if root.get("source_sha256") != trace.source_sha256:
        raise PlanFormatError("trace source hash does not match payload", code="trace.source_hash")
    return trace


def _trace_from_dict(value: Mapping[str, Any]) -> PreparationTrace:
    data = dict(value)
    try:
        diagnostics = tuple(_diagnostic(item) for item in _list(data.pop("diagnostics", [])))
        units = tuple(_unit(item) for item in _list(data.pop("units", [])))
        for key in ("structural_to_spoken", "spoken_to_structural"):
            raw = data.get(key, [])
            if not isinstance(raw, list) or any(type(item) is not int for item in raw):
                raise PlanFormatError(f"{key} must be an integer array", code="trace.field")
            data[key] = tuple(raw)
        for key in ("source_spans", "repairs"):
            raw = data.get(key, [])
            if not isinstance(raw, list) or any(not isinstance(item, Mapping) for item in raw):
                raise PlanFormatError(f"{key} must be an array of tables", code="trace.field")
            data[key] = tuple(dict(item) for item in raw)
        for key in ("compiler_plan", "renderability", "config"):
            raw = data.get(key, {})
            if not isinstance(raw, Mapping):
                raise PlanFormatError(f"{key} must be a table", code="trace.field")
            data[key] = dict(raw)
        warnings = data.get("warnings", [])
        if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
            raise PlanFormatError("warnings must be a string array", code="trace.field")
        data["warnings"] = tuple(warnings)
        data["diagnostics"] = diagnostics
        data["units"] = units
        return PreparationTrace(**data)
    except PlanFormatError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise PlanFormatError(f"invalid trace payload: {exc}", code="trace.payload") from exc


def _unit(value: Any) -> PreparationTraceUnit:
    if not isinstance(value, Mapping):
        raise PlanFormatError("trace unit must be a table", code="trace.unit")
    data = dict(value)
    languages = data.get("effective_languages", [])
    if not isinstance(languages, list) or any(not isinstance(item, str) for item in languages):
        raise PlanFormatError("effective_languages must be a string array", code="trace.unit")
    data["effective_languages"] = tuple(languages)
    data["transformations"] = tuple(
        PreparationChange(**item) for item in _mapping_list(data.get("transformations", []))
    )
    data["diagnostics"] = tuple(
        _diagnostic(item) for item in _mapping_list(data.get("diagnostics", []))
    )
    warnings = data.get("warnings", [])
    if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
        raise PlanFormatError("unit warnings must be a string array", code="trace.unit")
    data["warnings"] = tuple(warnings)
    return PreparationTraceUnit(**data)


def _diagnostic(value: Any) -> Diagnostic:
    if not isinstance(value, Mapping):
        raise PlanFormatError("trace diagnostic must be a table", code="trace.diagnostic")
    return Diagnostic(**dict(value))


def _list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise PlanFormatError("trace field must be an array", code="trace.field")
    return value


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    items = _list(value)
    if any(not isinstance(item, Mapping) for item in items):
        raise PlanFormatError("trace field must contain tables", code="trace.field")
    return items


__all__ = ["dumps_trace", "loads_trace"]
