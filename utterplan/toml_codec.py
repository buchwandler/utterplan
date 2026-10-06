"""Human-oriented TOML wire codec for semantic schema-v4 UtterancePlans.

This module deliberately owns all TOMLKit types and serialization policy. Its
wire projection is separate from the canonical semantic ``to_dict`` mapping.
"""

from __future__ import annotations

import datetime as _datetime
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.exceptions import ParseError

from .exceptions import PlanFormatError, UnsupportedSchemaError
from .model import UtterancePlan
from .versioning import FORMAT, SCHEMA_VERSION

_NULL_SENTINEL = "__utterplan_null__"
_RESERVED_PREFIX = "__utterplan_"
_ROOT_KEYS = frozenset(
    {
        "format",
        "schema_version",
        "plan_id",
        "producer",
        "config",
        "preparation",
        "language",
        "linguistic_run",
        "unit",
        "annotation",
        "semantic_boundary",
        "boundary",
        "marker",
        "token_stream",
        "diagnostic",
        "source",
        "texts",
        "document_metadata",
        "warnings",
    }
)
_TEXT_PATHS = {
    ("source", "text"),
    ("texts", "structural"),
    ("texts", "spoken"),
}


def to_toml_data(plan: UtterancePlan) -> dict[str, Any]:
    """Project *plan* to the deliberately compact schema-v4 TOML wire model."""
    semantic = plan.to_dict()
    segments_by_id = {segment["id"]: segment for segment in semantic["segments"]}

    result: dict[str, Any] = {
        "format": semantic["format"],
        "schema_version": semantic["schema_version"],
        "plan_id": semantic["plan_id"],
        "producer": _encode_freeform(semantic["producer"], "$.producer"),
        "config": _omit_none(semantic["config"]),
        "preparation": _preparation_to_wire(semantic["preparation"]),
        "language": [
            _range_to_wire(
                item,
                start="spoken_start",
                end="spoken_end",
                span="span",
                keep=("id", "language", "source"),
                path=f"$.languages[{index}]",
            )
            for index, item in enumerate(semantic["languages"])
        ],
        "linguistic_run": [
            _range_to_wire(
                item,
                start="token_start",
                end="token_end",
                span="token_span",
                keep=("language_run_id", "provider", "model", "provider_version", "model_version"),
                path=f"$.linguistic_runs[{index}]",
            )
            for index, item in enumerate(semantic["linguistic_runs"])
        ],
        "unit": [
            _unit_to_wire(unit, segments_by_id, index)
            for index, unit in enumerate(semantic["units"])
        ],
        "annotation": [
            _annotation_to_wire(item, index) for index, item in enumerate(semantic["annotations"])
        ],
        "semantic_boundary": [
            _semantic_boundary_to_wire(item, index)
            for index, item in enumerate(semantic["semantic_boundaries"])
        ],
        "boundary": [
            _boundary_to_wire(item, index) for index, item in enumerate(semantic["boundaries"])
        ],
        "marker": [_marker_to_wire(item, index) for index, item in enumerate(semantic["markers"])],
        "token_stream": {
            "items": [_token_to_wire(item, index) for index, item in enumerate(semantic["tokens"])]
        },
        "diagnostic": [
            _diagnostic_to_wire(item, index) for index, item in enumerate(semantic["diagnostics"])
        ],
        "source": dict(semantic["source"]),
        "texts": dict(semantic["texts"]),
        "document_metadata": _encode_freeform(semantic["document_metadata"], "$.document_metadata"),
        "warnings": list(semantic["warnings"]),
    }
    _check_toml_values(result, "$")
    return result


def from_toml_data(data: Mapping[str, object]) -> UtterancePlan:
    """Decode a TOML wire model into and validate a semantic schema-v4 plan."""
    plain = _plain_toml(data)
    _check_toml_values(plain, "$")
    root = _mapping(plain, "$")
    unknown = set(root) - _ROOT_KEYS
    if unknown:
        raise PlanFormatError(
            f"unknown top-level TOML fields: {sorted(unknown)}", code="field.unknown"
        )
    if root.get("format") != FORMAT:
        raise PlanFormatError("format must be 'utterplan'", code="format.invalid", path="$.format")
    version = root.get("schema_version")
    if type(version) is not int or version != SCHEMA_VERSION:
        raise UnsupportedSchemaError(version)

    try:
        semantic: dict[str, Any] = {
            "format": root["format"],
            "schema_version": version,
            "plan_id": root["plan_id"],
            "producer": _decode_freeform(_mapping(root["producer"], "$.producer"), "$.producer"),
            "config": _config_from_wire(_mapping(root["config"], "$.config")),
            "preparation": _preparation_from_wire(_mapping(root["preparation"], "$.preparation")),
            "languages": [
                _range_from_wire(
                    item,
                    start="spoken_start",
                    end="spoken_end",
                    span="span",
                    path=f"$.language[{i}]",
                )
                for i, item in enumerate(_list(root["language"], "$.language"))
            ],
            "linguistic_runs": [
                _range_from_wire(
                    item,
                    start="token_start",
                    end="token_end",
                    span="token_span",
                    path=f"$.linguistic_run[{i}]",
                )
                for i, item in enumerate(_list(root["linguistic_run"], "$.linguistic_run"))
            ],
            "units": [],
            "segments": [],
            "annotations": [
                _annotation_from_wire(item, i)
                for i, item in enumerate(_list(root["annotation"], "$.annotation"))
            ],
            "semantic_boundaries": [
                _semantic_boundary_from_wire(item, i)
                for i, item in enumerate(_list(root["semantic_boundary"], "$.semantic_boundary"))
            ],
            "boundaries": [
                _boundary_from_wire(item, i)
                for i, item in enumerate(_list(root["boundary"], "$.boundary"))
            ],
            "markers": [
                _marker_from_wire(item, i)
                for i, item in enumerate(_list(root["marker"], "$.marker"))
            ],
            "tokens": _tokens_from_wire(root["token_stream"]),
            "diagnostics": [
                _diagnostic_from_wire(item, i)
                for i, item in enumerate(_list(root["diagnostic"], "$.diagnostic"))
            ],
            "source": _mapping(root["source"], "$.source"),
            "texts": _mapping(root["texts"], "$.texts"),
            "document_metadata": _decode_freeform(
                _mapping(root["document_metadata"], "$.document_metadata"),
                "$.document_metadata",
            ),
            "warnings": _list(root["warnings"], "$.warnings"),
        }
        units: list[dict[str, Any]] = []
        segments: list[dict[str, Any]] = []
        for index, raw_unit in enumerate(_list(root["unit"], "$.unit")):
            unit, unit_segments = _unit_from_wire(raw_unit, index)
            units.append(unit)
            segments.extend(unit_segments)
        semantic["units"] = units
        semantic["segments"] = segments
        return UtterancePlan.from_dict(semantic)
    except KeyError as exc:
        raise PlanFormatError(
            f"required TOML field {exc.args[0]!r} is missing", code="field.required"
        ) from exc


def dumps_toml(plan: UtterancePlan) -> str:
    """Serialize a plan to deterministic, human-readable TOML text."""
    wire = to_toml_data(plan)
    document = tomlkit.document()
    for key, value in wire.items():
        document[key] = _toml_item(value, (key,))
    return tomlkit.dumps(document)


def loads_toml(value: object) -> UtterancePlan:
    """Parse TOML text and decode one schema-v4 UtterancePlan."""
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


def dump(plan: UtterancePlan, path: str | Path) -> None:
    """Atomically write a TOML plan to *path*."""
    from .atomic_io import atomic_write_text

    atomic_write_text(path, dumps_toml(plan), create_parent=True)


def load(path: str | Path) -> UtterancePlan:
    """Read and decode a TOML plan from *path*."""
    return loads_toml(Path(path).read_text(encoding="utf-8"))


def _preparation_to_wire(value: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "backend": value["backend"],
        "languages": list(value["languages"]),
        "warnings": list(value["warnings"]),
    }
    if value.get("version") is not None:
        result["version"] = value["version"]
    replacements: list[dict[str, Any]] = []
    for index, replacement in enumerate(value["replacements"]):
        item = _mapping(replacement, f"$.preparation.replacements[{index}]")
        wire_item: dict[str, Any] = {}
        _move_pair_to_span(
            item,
            wire_item,
            "source_start",
            "source_end",
            "source_span",
            required=False,
            path=f"$.preparation.replacements[{index}]",
        )
        _move_pair_to_span(
            item,
            wire_item,
            "output_start",
            "output_end",
            "output_span",
            required=False,
            path=f"$.preparation.replacements[{index}]",
        )
        for key, item_value in item.items():
            if key not in {"source_start", "source_end", "output_start", "output_end"}:
                wire_item[key] = _encode_freeform(
                    item_value, f"$.preparation.replacements[{index}].{key}"
                )
        replacements.append(wire_item)
    result["replacement"] = replacements
    return result


def _preparation_from_wire(value: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "backend": value["backend"],
        "version": value.get("version"),
        "languages": _list(value["languages"], "$.preparation.languages"),
        "warnings": _list(value["warnings"], "$.preparation.warnings"),
        "replacements": [],
    }
    replacements: list[dict[str, Any]] = []
    for index, raw in enumerate(_list(value["replacement"], "$.preparation.replacement")):
        item = dict(_mapping(raw, f"$.preparation.replacement[{index}]"))
        _move_span_to_pair(
            item,
            "source_span",
            "source_start",
            "source_end",
            required=False,
            path=f"$.preparation.replacement[{index}]",
        )
        _move_span_to_pair(
            item,
            "output_span",
            "output_start",
            "output_end",
            required=False,
            path=f"$.preparation.replacement[{index}]",
        )
        replacements.append(
            {
                key: _decode_freeform(item_value, f"$.preparation.replacement[{index}].{key}")
                for key, item_value in item.items()
            }
        )
    result["replacements"] = replacements
    return result


def _config_from_wire(config: Mapping[str, Any]) -> dict[str, Any]:
    result = _copy_mapping(config, "$.config")
    linguistics = dict(_mapping(result.get("linguistics", {}), "$.config.linguistics"))
    for key in ("use_spacy", "spacy_model", "spacy_model_size"):
        linguistics.setdefault(key, None)
    result["linguistics"] = linguistics
    ssmd = dict(_mapping(result.get("ssmd", {}), "$.config.ssmd"))
    ssmd.setdefault("pause_overrides", None)
    result["ssmd"] = ssmd
    return result


def _range_to_wire(
    item: Mapping[str, Any], *, start: str, end: str, span: str, keep: tuple[str, ...], path: str
) -> dict[str, Any]:
    result = {key: item[key] for key in keep if key in item and item[key] is not None}
    result[span] = _pair(item.get(start), item.get(end), path=path, required=True)
    return result


def _range_from_wire(item: object, *, start: str, end: str, span: str, path: str) -> dict[str, Any]:
    value = dict(_mapping(item, path))
    value[start], value[end] = _span(value.pop(span, None), path=f"{path}.{span}")
    return value


def _unit_to_wire(
    unit: Mapping[str, Any], segments_by_id: Mapping[str, Mapping[str, Any]], index: int
) -> dict[str, Any]:
    path = f"$.units[{index}]"
    segment_ids = _list(unit["segment_ids"], f"{path}.segment_ids")
    try:
        nested_segments = [
            _segment_to_wire(segments_by_id[segment_id], f"{path}.segments[{offset}]")
            for offset, segment_id in enumerate(segment_ids)
        ]
    except KeyError as exc:
        raise PlanFormatError(
            f"unit references unknown segment {exc.args[0]!r}",
            code="unit.unknown_segment",
            path=path,
        ) from exc
    return {
        "id": unit["id"],
        "index": unit["index"],
        "kind": unit["kind"],
        "span": [unit["spoken_start"], unit["spoken_end"]],
        "content_hash": unit["content_hash"],
        "content_hash_schema": unit["content_hash_schema"],
        "markers": list(unit["marker_ids"]),
        "segment": nested_segments,
    }


def _unit_from_wire(item: object, index: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = f"$.unit[{index}]"
    value = _mapping(item, path)
    start, end = _span(value.get("span"), path=f"{path}.span")
    segments = [
        _segment_from_wire(segment, f"{path}.segment[{segment_index}]")
        for segment_index, segment in enumerate(_list(value.get("segment", []), f"{path}.segment"))
    ]
    unit = {
        "id": value["id"],
        "index": value["index"],
        "kind": value["kind"],
        "spoken_start": start,
        "spoken_end": end,
        "segment_ids": [segment["id"] for segment in segments],
        "marker_ids": _list(value.get("markers", []), f"{path}.markers"),
        "content_hash": value["content_hash"],
        "content_hash_schema": value["content_hash_schema"],
    }
    return unit, segments


def _segment_to_wire(item: Mapping[str, Any], path: str) -> dict[str, Any]:
    result = {
        "id": item["id"],
        "text": item["text"],
        "span": _pair(item.get("spoken_start"), item.get("spoken_end"), path=path, required=True),
        "language": item["language"],
        "paragraph": item["paragraph"],
        "sentence": item["sentence"],
        "clause": item["clause"],
        "tokens": list(item["token_indices"]),
        "annotations": list(item["annotation_ids"]),
        "pause_before": _omit_none(item["pause_before"]),
        "pause_after": _omit_none(item["pause_after"]),
        "directives": _omit_none(item["directives"]),
    }
    _move_pair_to_span(
        item,
        result,
        "structural_start",
        "structural_end",
        "structural_span",
        required=False,
        path=path,
    )
    return result


def _segment_from_wire(item: object, path: str) -> dict[str, Any]:
    value = dict(_mapping(item, path))
    start, end = _span(value.pop("span", None), path=f"{path}.span")
    result = {
        "id": value["id"],
        "text": value["text"],
        "spoken_start": start,
        "spoken_end": end,
        "language": value["language"],
        "paragraph": value["paragraph"],
        "sentence": value["sentence"],
        "clause": value["clause"],
        "token_indices": _list(value.get("tokens", []), f"{path}.tokens"),
        "annotation_ids": _list(value.get("annotations", []), f"{path}.annotations"),
        "pause_before": value["pause_before"],
        "pause_after": value["pause_after"],
        "directives": value.get("directives", {}),
    }
    _move_span_to_pair(
        value, "structural_span", "structural_start", "structural_end", required=False, path=path
    )
    for key in ("structural_start", "structural_end"):
        if key in value:
            result[key] = value[key]
    return result


def _annotation_to_wire(item: Mapping[str, Any], index: int) -> dict[str, Any]:
    path = f"$.annotations[{index}]"
    result: dict[str, Any] = {
        "id": item["id"],
        "kind": item["kind"],
        "structural_span": _pair(
            item.get("structural_start"), item.get("structural_end"), path=path, required=True
        ),
        "attrs": _encode_freeform(item["attrs"], f"{path}.attrs"),
    }
    _move_pair_to_span(
        item, result, "spoken_start", "spoken_end", "spoken_span", required=False, path=path
    )
    _move_pair_to_span(
        item, result, "source_start", "source_end", "source_span", required=False, path=path
    )
    if item.get("source_node_id") is not None:
        result["source_node_id"] = item["source_node_id"]
    return result


def _annotation_from_wire(item: object, index: int) -> dict[str, Any]:
    path = f"$.annotation[{index}]"
    value = dict(_mapping(item, path))
    structural_start, structural_end = _span(
        value.pop("structural_span", None), path=f"{path}.structural_span"
    )
    result: dict[str, Any] = {
        "id": value["id"],
        "kind": value["kind"],
        "attrs": _decode_freeform(_mapping(value["attrs"], f"{path}.attrs"), f"{path}.attrs"),
        "structural_start": structural_start,
        "structural_end": structural_end,
    }
    for wire_name, first, second in (
        ("spoken_span", "spoken_start", "spoken_end"),
        ("source_span", "source_start", "source_end"),
    ):
        if wire_name in value:
            result[first], result[second] = _span(value[wire_name], path=f"{path}.{wire_name}")
    if "source_node_id" in value:
        result["source_node_id"] = value["source_node_id"]
    return result


def _semantic_boundary_to_wire(item: Mapping[str, Any], index: int) -> dict[str, Any]:
    result = {key: item[key] for key in ("id", "position", "kind", "origin")}
    if item.get("language_run_id") is not None:
        result["language_run_id"] = item["language_run_id"]
    if item.get("attrs"):
        result["attrs"] = _encode_freeform(item["attrs"], f"$.semantic_boundaries[{index}].attrs")
    return result


def _semantic_boundary_from_wire(item: object, index: int) -> dict[str, Any]:
    path = f"$.semantic_boundary[{index}]"
    value = dict(_mapping(item, path))
    result = {key: value[key] for key in ("id", "position", "kind", "origin")}
    result["language_run_id"] = value.get("language_run_id")
    if "attrs" in value:
        result["attrs"] = _decode_freeform(
            _mapping(value["attrs"], f"{path}.attrs"), f"{path}.attrs"
        )
    return result


def _boundary_to_wire(item: Mapping[str, Any], index: int) -> dict[str, Any]:
    result = {key: item[key] for key in ("id", "position", "kind", "origin")}
    for key in ("seconds", "strength"):
        if item.get(key) is not None:
            result[key] = item[key]
    if item.get("attrs"):
        result["attrs"] = _encode_freeform(item["attrs"], f"$.boundaries[{index}].attrs")
    return result


def _boundary_from_wire(item: object, index: int) -> dict[str, Any]:
    path = f"$.boundary[{index}]"
    value = _mapping(item, path)
    result = {key: value[key] for key in ("id", "position", "kind", "origin")}
    result["seconds"] = value.get("seconds")
    result["strength"] = value.get("strength")
    if "attrs" in value:
        result["attrs"] = _decode_freeform(
            _mapping(value["attrs"], f"{path}.attrs"), f"{path}.attrs"
        )
    return result


def _marker_to_wire(item: Mapping[str, Any], index: int) -> dict[str, Any]:
    result = {"id": item["id"], "name": item["name"], "position": item["spoken_position"]}
    if item.get("attrs"):
        result["attrs"] = _encode_freeform(item["attrs"], f"$.markers[{index}].attrs")
    return result


def _marker_from_wire(item: object, index: int) -> dict[str, Any]:
    path = f"$.marker[{index}]"
    value = _mapping(item, path)
    result = {"id": value["id"], "name": value["name"], "spoken_position": value["position"]}
    if "attrs" in value:
        result["attrs"] = _decode_freeform(
            _mapping(value["attrs"], f"{path}.attrs"), f"{path}.attrs"
        )
    return result


def _token_to_wire(item: Mapping[str, Any], index: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if item.get("id") is not None:
        result["id"] = item["id"]
    result["span"] = _pair(
        item["spoken_start"], item["spoken_end"], path=f"$.tokens[{index}]", required=True
    )
    result["text"] = item["text"]
    for key in ("lemma", "pos", "tag", "language", "morph"):
        if item.get(key) is not None:
            result[key] = item[key]
    return result


def _tokens_from_wire(value: object) -> list[dict[str, Any]]:
    table = _mapping(value, "$.token_stream")
    unknown = set(table) - {"items"}
    if unknown:
        raise PlanFormatError(
            f"unknown token_stream fields: {sorted(unknown)}",
            code="field.unknown",
            path="$.token_stream",
        )
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(_list(table.get("items"), "$.token_stream.items")):
        path = f"$.token_stream.items[{index}]"
        item = dict(_mapping(raw, path))
        start, end = _span(item.pop("span", None), path=f"{path}.span")
        result.append({"spoken_start": start, "spoken_end": end, **item})
    return result


def _diagnostic_to_wire(item: Mapping[str, Any], index: int) -> dict[str, Any]:
    result = {key: item[key] for key in ("code", "severity", "message")}
    if item.get("path") is not None:
        result["path"] = item["path"]
    _move_pair_to_span(
        item,
        result,
        "source_start",
        "source_end",
        "source_span",
        required=False,
        path=f"$.diagnostics[{index}]",
    )
    for key in ("line", "column", "hint"):
        if item.get(key) is not None:
            result[key] = item[key]
    return result


def _diagnostic_from_wire(item: object, index: int) -> dict[str, Any]:
    path = f"$.diagnostic[{index}]"
    value = dict(_mapping(item, path))
    result = {key: value[key] for key in ("code", "severity", "message")}
    result["path"] = value.get("path")
    if "source_span" in value:
        result["source_start"], result["source_end"] = _span(
            value["source_span"], path=f"{path}.source_span"
        )
    for key in ("line", "column", "hint"):
        if key in value:
            result[key] = value[key]
    return result


def _move_pair_to_span(
    source: Mapping[str, Any],
    target: dict[str, Any],
    start: str,
    end: str,
    span: str,
    *,
    required: bool,
    path: str,
) -> None:
    first, second = source.get(start), source.get(end)
    if first is None and second is None:
        if required:
            raise PlanFormatError(
                f"{start} and {end} are required", code="field.required", path=path
            )
        return
    target[span] = _pair(first, second, path=path, required=True)


def _move_span_to_pair(
    source: dict[str, Any], span: str, start: str, end: str, *, required: bool, path: str
) -> None:
    if span not in source:
        if required:
            raise PlanFormatError(f"{span} is required", code="field.required", path=path)
        return
    first, second = _span(source[span], path=f"{path}.{span}")
    source[start], source[end] = first, second
    source.pop(span)


def _pair(first: object, second: object, *, path: str, required: bool) -> list[int] | None:
    if first is None and second is None and not required:
        return None
    if type(first) is not int or type(second) is not int:
        raise PlanFormatError(
            "span endpoints must both be integers", code="span.invalid", path=path
        )
    return [first, second]


def _span(value: object, *, path: str) -> tuple[int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(type(point) is not int for point in value)
    ):
        raise PlanFormatError(
            "span must contain exactly two integers", code="span.invalid", path=path
        )
    return value[0], value[1]


def _encode_freeform(value: Any, path: str) -> Any:
    if value is None:
        return {_NULL_SENTINEL: True}
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PlanFormatError(
                    "free-form mapping keys must be strings", code="toml.value", path=path
                )
            if key.startswith(_RESERVED_PREFIX):
                raise PlanFormatError(
                    f"reserved metadata key {key!r}", code="toml.reserved_key", path=path
                )
            result[key] = _encode_freeform(item, f"{path}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [_encode_freeform(item, f"{path}[{index}]") for index, item in enumerate(value)]
    _check_toml_values(value, path)
    return value


def _decode_freeform(value: Any, path: str) -> Any:
    if isinstance(value, Mapping):
        if _NULL_SENTINEL in value:
            if len(value) == 1 and value[_NULL_SENTINEL] is True:
                return None
            raise PlanFormatError(
                "conflicting reserved metadata sentinel", code="toml.reserved_key", path=path
            )
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PlanFormatError(
                    "free-form mapping keys must be strings", code="toml.value", path=path
                )
            if key.startswith(_RESERVED_PREFIX):
                raise PlanFormatError(
                    f"reserved metadata key {key!r}", code="toml.reserved_key", path=path
                )
            result[key] = _decode_freeform(item, f"{path}.{key}")
        return result
    if isinstance(value, list):
        return [_decode_freeform(item, f"{path}[{index}]") for index, item in enumerate(value)]
    return value


def _omit_none(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _omit_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, (list, tuple)):
        return [_omit_none(item) for item in value]
    return value


def _check_toml_values(value: Any, path: str) -> None:
    if value is None:
        raise PlanFormatError("TOML wire data cannot contain null", code="toml.null", path=path)
    if isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PlanFormatError(
                "non-finite floats are not supported", code="toml.float", path=path
            )
        return
    if isinstance(value, (_datetime.datetime, _datetime.date, _datetime.time)):
        raise PlanFormatError(
            "TOML date/time values are not part of the plan data model",
            code="toml.datetime",
            path=path,
        )
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise PlanFormatError(
                    "TOML table keys must be strings", code="toml.value", path=path
                )
            _check_toml_values(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check_toml_values(item, f"{path}[{index}]")
        return
    raise PlanFormatError(
        f"unsupported TOML value type {type(value).__name__}", code="toml.value", path=path
    )


def _plain_toml(value: Any) -> Any:
    if hasattr(value, "unwrap"):
        value = value.unwrap()
    if isinstance(value, Mapping):
        return {key: _plain_toml(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_toml(item) for item in value]
    return value


def _toml_item(value: Any, path: tuple[str, ...]) -> Any:
    if isinstance(value, Mapping):
        return {key: _toml_item(item, (*path, key)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        if path == ("token_stream", "items"):
            array = tomlkit.array()
            array.multiline(True)
            for item in value:
                if not isinstance(item, Mapping):
                    raise PlanFormatError(
                        "token stream items must be tables",
                        code="toml.value",
                        path="$.token_stream.items",
                    )
                inline = tomlkit.inline_table()
                for key, item_value in item.items():
                    inline[key] = _toml_item(item_value, (*path, str(key)))
                array.append(inline)
            return array
        return [_toml_item(item, path) for item in value]
    if isinstance(value, str) and path in _TEXT_PATHS:
        return tomlkit.string(value, multiline=True)
    return value


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PlanFormatError("expected a TOML table", code="field.type", path=path)
    return value


def _copy_mapping(value: Mapping[str, Any], path: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise PlanFormatError("table keys must be strings", code="field.type", path=path)
        result[key] = item
    return result


def _list(value: object, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise PlanFormatError("expected a TOML array", code="field.type", path=path)
    return value


__all__ = ["dump", "dumps_toml", "from_toml_data", "load", "loads_toml", "to_toml_data"]
