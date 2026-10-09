from __future__ import annotations

import datetime as _datetime
import math
from collections.abc import Mapping
from typing import Any

import tomlkit
from tomlkit.exceptions import ParseError
from tomlkit.items import DottedKey

from ..exceptions import PlanFormatError
from ..model import FlowPlan

_ROOT_KEYS = frozenset(
    {
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
    }
)
_NULL_SENTINEL = "__utterplan_null__"
_RESERVED_PREFIX = "__utterplan_"
_DIRECTIVE_KEYS = frozenset(
    {
        "voice",
        "pronunciation",
        "prosody",
        "emphasis",
        "say_as",
        "substitution",
        "audio",
        "extensions",
    }
)


def _error(message: str, *, code: str, path: str = "$") -> PlanFormatError:
    return PlanFormatError(message, code=code, path=path)


def _plain(value: Any) -> Any:
    if hasattr(value, "unwrap"):
        value = value.unwrap()
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _omit_none(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _omit_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, (list, tuple)):
        return [_omit_none(item) for item in value]
    return value


def _encode_freeform(value: Any, path: str) -> Any:
    if value is None:
        return {_NULL_SENTINEL: True}
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _error("free-form keys must be strings", code="toml.value", path=path)
            if key.startswith(_RESERVED_PREFIX):
                raise _error(f"reserved metadata key {key!r}", code="toml.reserved_key", path=path)
            result[key] = _encode_freeform(item, f"{path}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [_encode_freeform(item, f"{path}[{index}]") for index, item in enumerate(value)]
    _check_values(value, path)
    return value


def _decode_freeform(value: Any, path: str) -> Any:
    if isinstance(value, Mapping):
        if _NULL_SENTINEL in value:
            if len(value) == 1 and value[_NULL_SENTINEL] is True:
                return None
            raise _error("conflicting null sentinel", code="toml.reserved_key", path=path)
        result = {}
        for key, item in value.items():
            if not isinstance(key, str) or key.startswith(_RESERVED_PREFIX):
                raise _error("reserved free-form key", code="toml.reserved_key", path=path)
            result[key] = _decode_freeform(item, f"{path}.{key}")
        return result
    if isinstance(value, list):
        return [_decode_freeform(item, f"{path}[{index}]") for index, item in enumerate(value)]
    return value


def _check_values(value: Any, path: str = "$") -> None:
    if value is None:
        raise _error("TOML values cannot contain null", code="toml.null", path=path)
    if isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _error("non-finite floats are not supported", code="toml.float", path=path)
        return
    if isinstance(value, (_datetime.date, _datetime.time, _datetime.datetime)):
        raise _error(
            "TOML date/time values are not part of the plan model", code="toml.datetime", path=path
        )
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise _error("TOML mapping keys must be strings", code="toml.value", path=path)
            _check_values(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check_values(item, f"{path}[{index}]")
        return
    raise _error(
        f"unsupported TOML value type {type(value).__name__}", code="toml.value", path=path
    )


def _sparse_column(tokens: tuple[Any, ...], field: str) -> list[list[Any]]:
    return [
        [index, value]
        for index, token in enumerate(tokens)
        if (value := getattr(token, field)) is not None
    ]


def _token_columns(segment: Any) -> dict[str, Any]:
    tokens = segment.tokens
    if not tokens:
        return {}
    columns: dict[str, Any] = {"span": [[token.start, token.end] for token in tokens]}
    for field in ("pos", "tag"):
        values = [getattr(token, field) for token in tokens]
        if all(value is not None for value in values):
            columns[field] = values
        elif any(value is not None for value in values):
            columns[field] = _sparse_column(tokens, field)
    lemmas: list[list[Any]] = []
    for index, token in enumerate(tokens):
        lemma = token.lemma
        if lemma is None:
            # Empty sparse values explicitly preserve an unknown lemma; absent entries derive casefolded surface.
            lemmas.append([index, ""])
        elif lemma != token.surface(segment.text).casefold():
            lemmas.append([index, lemma])
    if lemmas:
        columns["lemma"] = lemmas
    morph = _sparse_column(tokens, "morph")
    if morph:
        columns["morph"] = morph
    return columns


def _segment_to_wire(segment: Any, default_language: str) -> dict[str, Any]:
    result: dict[str, Any] = {"text": segment.text}
    if segment.language != default_language:
        result["language"] = segment.language
    for key in ("pause_before", "pause_after"):
        value = getattr(segment, key)
        if value is not None:
            result[key] = value.to_dict()
    for key, value in segment.directives.to_dict().items():
        result[key] = _omit_none(value)
    if segment.markers:
        result["marker"] = list(segment.markers)
    if segment.heading is not None:
        result["heading"] = segment.heading
    token = _token_columns(segment)
    if token:
        result["token"] = token
    return result


def to_v5_toml_data(plan: FlowPlan) -> dict[str, Any]:
    if not isinstance(plan, FlowPlan):
        raise _error("v5 TOML serialization requires a FlowPlan", code="plan.type")
    plan.validate()
    result: dict[str, Any] = {
        "format": plan.format,
        "schema_version": plan.schema_version,
        "plan_id": plan.plan_id,
        "language": plan.language,
        "unit": plan.unit,
        "hash_schema": plan.hash_schema,
        "document": {
            **{key: value for key, value in plan.document.to_dict().items() if key != "semantics"},
            "semantics": _encode_freeform(plan.document.semantics, "$.document.semantics"),
        },
        "flow": [
            {
                "hash": unit.content_hash,
                "segment": [_segment_to_wire(segment, plan.language) for segment in unit.segments],
            }
            for unit in plan.flow
        ],
    }
    if plan.linguistics:
        result["linguistics"] = [item.to_dict() for item in plan.linguistics]
    if plan.producer:
        result["producer"] = dict(plan.producer)
    if plan.warnings:
        result["warnings"] = list(plan.warnings)
    _check_values(result)
    return result


def _decode_sparse(
    raw: Any,
    *,
    field: str,
    count: int,
    path: str,
) -> dict[int, str]:
    if not isinstance(raw, list):
        raise _error(f"token {field} must be an array", code="token.column", path=path)
    result: dict[int, str] = {}
    previous = -1
    for entry_index, entry in enumerate(raw):
        entry_path = f"{path}[{entry_index}]"
        if not isinstance(entry, list) or len(entry) != 2:
            raise _error(
                "sparse token entries must be [index, value] pairs",
                code="token.sparse",
                path=entry_path,
            )
        index, value = entry
        if type(index) is not int or not 0 <= index < count or index <= previous:
            raise _error(
                "sparse token indices must be valid, unique, and ascending",
                code="token.sparse",
                path=entry_path,
            )
        if not isinstance(value, str):
            raise _error(
                "sparse token values must be strings", code="token.column", path=entry_path
            )
        result[index] = value
        previous = index
    return result


def _decode_positional_column(
    raw: Any,
    *,
    field: str,
    count: int,
    path: str,
) -> dict[int, str]:
    if not isinstance(raw, list):
        raise _error(f"token {field} must be an array", code="token.column", path=path)
    if raw and isinstance(raw[0], list):
        return _decode_sparse(raw, field=field, count=count, path=path)
    if len(raw) != count or any(not isinstance(item, str) for item in raw):
        raise _error(
            f"dense token {field} column must match token count", code="token.column", path=path
        )
    return dict(enumerate(raw))


def _tokens_from_wire(value: Any, text: str, path: str) -> list[dict[str, Any]]:
    if not isinstance(value, Mapping):
        raise _error("token block must be an object", code="token.type", path=path)
    unknown = set(value) - {"span", "pos", "tag", "lemma", "morph"}
    if unknown:
        raise _error(f"unknown token columns: {sorted(unknown)}", code="field.unknown", path=path)
    spans = value.get("span")
    if not isinstance(spans, list) or not spans:
        raise _error(
            "token span column is required when tokens exist", code="token.span", path=path
        )
    normalized_spans: list[tuple[int, int]] = []
    previous_end = 0
    for index, span in enumerate(spans):
        span_path = f"{path}.span[{index}]"
        if (
            not isinstance(span, list)
            or len(span) != 2
            or any(type(point) is not int for point in span)
        ):
            raise _error("token span must be [start, end]", code="token.span", path=span_path)
        start, end = span
        if start < previous_end or end <= start or end > len(text):
            raise _error(
                "token spans must be ordered, non-overlapping, and within segment text",
                code="token.span",
                path=span_path,
            )
        normalized_spans.append((start, end))
        previous_end = end
    count = len(normalized_spans)
    columns: dict[str, dict[int, str]] = {}
    for field in ("pos", "tag"):
        if field in value:
            columns[field] = _decode_positional_column(
                value[field], field=field, count=count, path=f"{path}.{field}"
            )
    for field in ("lemma", "morph"):
        if field in value:
            columns[field] = _decode_sparse(
                value[field], field=field, count=count, path=f"{path}.{field}"
            )
    tokens: list[dict[str, Any]] = []
    lemma_entries = columns.get("lemma", {})
    for index, (start, end) in enumerate(normalized_spans):
        token: dict[str, Any] = {"start": start, "end": end}
        for field in ("pos", "tag", "morph"):
            entries = columns.get(field, {})
            if index in entries:
                token[field] = entries[index]
        if index in lemma_entries:
            if lemma_entries[index] != "":
                token["lemma"] = lemma_entries[index]
        else:
            token["lemma"] = text[start:end].casefold()
        tokens.append(token)
    return tokens


def _segment_from_wire(value: Any, default_language: str, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _error("flow segment must be a table", code="flow.segment", path=path)
    allowed = {
        "text",
        "language",
        "pause_before",
        "pause_after",
        "marker",
        "heading",
        "token",
        *_DIRECTIVE_KEYS,
    }
    unknown = set(value) - allowed
    if unknown:
        raise _error(
            f"unknown flow segment fields: {sorted(unknown)}", code="field.unknown", path=path
        )
    text = value.get("text")
    if not isinstance(text, str):
        raise _error("segment text must be a string", code="segment.text", path=path)
    result: dict[str, Any] = {
        "text": text,
        "language": value.get("language", default_language),
        "directives": {key: _plain(value[key]) for key in _DIRECTIVE_KEYS if key in value},
        "tokens": _tokens_from_wire(value["token"], text, f"{path}.token")
        if "token" in value
        else [],
        "markers": value.get("marker", []),
    }
    for key in ("pause_before", "pause_after", "heading"):
        if key in value:
            result[key] = _plain(value[key])
    return result


def from_v5_toml_data(data: Mapping[str, Any]) -> FlowPlan:
    plain = _plain(data)
    _check_values(plain)
    if not isinstance(plain, Mapping):
        raise _error("TOML root must be a table", code="toml.root")
    unknown = set(plain) - _ROOT_KEYS
    if unknown:
        raise _error(f"unknown top-level TOML fields: {sorted(unknown)}", code="field.unknown")
    required = {"format", "schema_version", "plan_id", "language", "unit", "hash_schema", "flow"}
    missing = required - set(plain)
    if missing:
        raise _error(f"required TOML fields are missing: {sorted(missing)}", code="field.required")
    if plain.get("format") != "utterplan" or plain.get("schema_version") != 5:
        raise _error("expected schema-v5 UtterPlan TOML", code="schema.version")
    language = plain.get("language")
    if not isinstance(language, str) or not language:
        raise _error("language must be a non-empty string", code="language.invalid")

    raw_document = plain.get("document", {})
    if not isinstance(raw_document, Mapping):
        raise _error("document must be a table", code="document.type")
    document = dict(raw_document)
    semantics = document.get("semantics", {})
    document["semantics"] = _decode_freeform(semantics, "$.document.semantics")

    raw_linguistics = plain.get("linguistics", [])
    if not isinstance(raw_linguistics, list):
        raise _error("linguistics must be an array of tables", code="linguistics.type")
    raw_flow = plain.get("flow")
    if not isinstance(raw_flow, list):
        raise _error("flow must be an array of tables", code="flow.type")
    flow: list[dict[str, Any]] = []
    for unit_index, raw_unit in enumerate(raw_flow):
        path = f"$.flow[{unit_index}]"
        if not isinstance(raw_unit, Mapping):
            raise _error("flow unit must be a table", code="flow.unit", path=path)
        unknown_unit = set(raw_unit) - {"hash", "segment"}
        if unknown_unit:
            raise _error(
                f"unknown flow unit fields: {sorted(unknown_unit)}", code="field.unknown", path=path
            )
        raw_segments = raw_unit.get("segment", [])
        if not isinstance(raw_segments, list):
            raise _error("flow.segment must be an array of tables", code="flow.segments", path=path)
        segments = [
            _segment_from_wire(segment, language, f"{path}.segment[{segment_index}]")
            for segment_index, segment in enumerate(raw_segments)
        ]
        flow.append({"segments": segments, "hash": raw_unit.get("hash")})

    semantic: dict[str, Any] = {
        "format": plain["format"],
        "schema_version": plain["schema_version"],
        "plan_id": plain["plan_id"],
        "language": language,
        "unit": plain["unit"],
        "hash_schema": plain["hash_schema"],
        "document": document,
        "linguistics": raw_linguistics,
        "flow": flow,
    }
    for key in ("producer", "warnings"):
        if key in plain:
            semantic[key] = plain[key]
    return FlowPlan.from_dict(semantic)


def _toml_value(value: Any, *, inline: bool = False) -> Any:
    if isinstance(value, Mapping):
        table = tomlkit.inline_table() if inline else tomlkit.table()
        for key, item in value.items():
            table[key] = _toml_value(item, inline=True)
        return table
    if isinstance(value, (list, tuple)):
        array = tomlkit.array()
        for item in value:
            array.append(_toml_value(item, inline=True))
        return array
    return value


def dumps_v5_toml(plan: FlowPlan) -> str:
    wire = to_v5_toml_data(plan)
    document = tomlkit.document()
    for key in ("format", "schema_version", "plan_id", "language", "unit", "hash_schema"):
        document[key] = wire[key]
    for key in ("producer", "warnings"):
        if key in wire:
            document[key] = _toml_value(wire[key])

    document_table = tomlkit.table()
    for key, value in wire["document"].items():
        document_table[key] = _toml_value(value, inline=isinstance(value, Mapping))
    document["document"] = document_table

    if wire.get("linguistics"):
        linguistic_array = tomlkit.aot()
        for item in wire["linguistics"]:
            table = tomlkit.table()
            for key, value in item.items():
                table[key] = value
            linguistic_array.append(table)
        document["linguistics"] = linguistic_array

    flow_array = tomlkit.aot()
    for unit in wire["flow"]:
        table = tomlkit.table()
        table["hash"] = unit["hash"]
        segment_array = tomlkit.aot()
        for segment in unit["segment"]:
            segment_table = tomlkit.table()
            for key, value in segment.items():
                if key == "token":
                    for column, values in value.items():
                        segment_table[DottedKey([tomlkit.key("token"), tomlkit.key(column)])] = (
                            _toml_value(values)
                        )
                else:
                    segment_table[key] = _toml_value(value, inline=isinstance(value, Mapping))
            segment_array.append(segment_table)
        table["segment"] = segment_array
        flow_array.append(table)
    document["flow"] = flow_array if wire["flow"] else tomlkit.array()
    return tomlkit.dumps(document)


def loads_v5_toml(value: str) -> FlowPlan:
    try:
        parsed = tomlkit.parse(value)
    except ParseError as exc:
        line = getattr(exc, "line", None)
        column = getattr(exc, "col", None)
        location = f"line {line}, column {column}: " if line is not None else ""
        raise _error(f"{location}{exc}", code="toml.invalid") from exc
    return from_v5_toml_data(parsed.unwrap())


__all__ = ["dumps_v5_toml", "from_v5_toml_data", "loads_v5_toml", "to_v5_toml_data"]
