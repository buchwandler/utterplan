from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

UNIT_HASH_SCHEMA = "utterplan-unit-v3"
LEGACY_UNIT_HASH_SCHEMA = "utterplan-unit-v2"


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def semantic_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


FLOW_HASH_SCHEMA = "utterplan-flow-v1"


def _flow_pause_semantics(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if isinstance(value, Mapping):
        if value.get("type") == "timed":
            return {"type": "timed", "time": value.get("time")}
        return {key: item for key, item in value.items() if key in {"type", "time"}}
    return value


def flow_unit_hash(segments: Any) -> str:
    """Hash one v5 flow unit using only its locally owned executable semantics."""
    values: list[dict[str, Any]] = []
    for segment in segments:
        value = _mapping(segment) or {}
        semantic: dict[str, Any] = {
            "text": _get(value, "text"),
            "language": _get(value, "language"),
            "directives": _plain_semantic(_get(value, "directives", {})) or {},
            "tokens": [_plain_semantic(token) for token in _get(value, "tokens", ())],
            "markers": list(_get(value, "markers", ())),
        }
        for key in ("pause_before", "pause_after"):
            pause = _flow_pause_semantics(_get(value, key))
            if pause is not None:
                semantic[key] = pause
        heading = _get(value, "heading")
        if heading is not None:
            semantic["heading"] = heading
        values.append(semantic)
    return semantic_hash({"segments": values})


def flow_plan_id(data: Mapping[str, Any]) -> str:
    """Hash only renderer-visible v5 semantics, excluding provenance and diagnostics."""
    document = data.get("document", {})
    semantics = document.get("semantics", {}) if isinstance(document, Mapping) else {}
    identity = {
        "format": data.get("format"),
        "schema_version": data.get("schema_version"),
        "language": data.get("language"),
        "unit": data.get("unit"),
        "hash_schema": data.get("hash_schema", FLOW_HASH_SCHEMA),
        "document_semantics": _plain_semantic(semantics) if isinstance(semantics, Mapping) else {},
        "flow": [
            {
                "segments": [
                    _flow_segment_semantics(segment) for segment in _get(unit, "segments", ())
                ],
            }
            for unit in data.get("flow", ())
        ],
    }
    return semantic_hash(identity)


def _flow_segment_semantics(segment: Any) -> dict[str, Any]:
    value = _mapping(segment) or {}
    result: dict[str, Any] = {
        "text": _get(value, "text"),
        "language": _get(value, "language"),
        "directives": _plain_semantic(_get(value, "directives", {})) or {},
        "tokens": [_plain_semantic(token) for token in _get(value, "tokens", ())],
        "markers": list(_get(value, "markers", ())),
    }
    for key in ("pause_before", "pause_after"):
        pause = _flow_pause_semantics(_get(value, key))
        if pause is not None:
            result[key] = pause
    heading = _get(value, "heading")
    if heading is not None:
        result["heading"] = heading
    return result


def unit_hash_payload(unit: Any) -> dict[str, Any]:
    segments = tuple(_get(unit, "segments", ()))
    marker_values: Any = _get(unit, "marker_values", None)
    if marker_values is None:
        marker_values = _get(unit, "marker_ids", ())
    return _unit_hash_payload_from_parts(
        _get(unit, "spoken_start", _first_segment_position(segments, "spoken_start")),
        _get(unit, "spoken_end", _last_segment_position(segments, "spoken_end")),
        segments,
        marker_values,
        _get(unit, "tokens", ()),
        _get(unit, "semantic_boundaries", ()),
    )


def unit_hash_payload_from_serialized(
    unit: Mapping[str, Any], plan: Mapping[str, Any]
) -> dict[str, Any]:
    """Build the current unit payload from serialized plain plan data."""
    segments_by_id = {
        segment["id"]: segment
        for segment in plan.get("segments", ())
        if isinstance(segment, Mapping) and isinstance(segment.get("id"), str)
    }
    markers_by_id = {
        marker["id"]: marker
        for marker in plan.get("markers", ())
        if isinstance(marker, Mapping) and isinstance(marker.get("id"), str)
    }
    segments = tuple(segments_by_id[item_id] for item_id in unit.get("segment_ids", ()))
    markers = tuple(markers_by_id[item_id] for item_id in unit.get("marker_ids", ()))
    start = unit.get("spoken_start", _first_segment_position(segments, "spoken_start"))
    end = unit.get("spoken_end", _last_segment_position(segments, "spoken_end"))
    return _unit_hash_payload_from_parts(
        start,
        end,
        segments,
        markers,
        plan.get("tokens", ()),
        plan.get("semantic_boundaries", ()),
    )


def _unit_hash_payload_from_parts(
    spoken_start: int,
    spoken_end: int,
    segments: Any,
    markers: Any,
    tokens: Any,
    semantic_boundaries: Any,
) -> dict[str, Any]:
    marker_values: list[Any] = []
    for marker in markers:
        value = _mapping(marker)
        if value is None:
            marker_values.append(marker)
        else:
            value.pop("id", None)
            marker_values.append(value)
    token_values = [
        {
            "text": _get(token, "text"),
            "language": _get(token, "language"),
            "lemma": _get(token, "lemma"),
            "pos": _get(token, "pos"),
            "tag": _get(token, "tag"),
            "morph": _get(token, "morph"),
        }
        for segment in segments
        for token in (_item(tokens, index) for index in _get(segment, "token_indices", ()))
    ]
    relative_boundaries = [
        {
            "kind": _get(boundary, "kind"),
            "position": _get(boundary, "position") - spoken_start,
        }
        for boundary in semantic_boundaries
        if type(_get(boundary, "position")) is int
        and spoken_start < _get(boundary, "position") < spoken_end
    ]
    relative_boundaries.sort(key=lambda item: (item["position"], item["kind"]))
    return {
        "hash_schema": UNIT_HASH_SCHEMA,
        "segments": [
            {
                "text": _get(segment, "text"),
                "language": _get(segment, "language"),
                "directives": _mapping(_get(segment, "directives", {})) or {},
                "pause_before": _plain_semantic(_get(segment, "pause_before")),
                "pause_after": _plain_semantic(_get(segment, "pause_after")),
            }
            for segment in segments
        ],
        "markers": marker_values,
        "tokens": token_values,
        "semantic_boundaries": relative_boundaries,
    }


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _plain_semantic(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {key: _plain_semantic(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain_semantic(item) for item in value]
    return value


def _mapping(value: Any) -> dict[str, Any] | None:
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if isinstance(value, Mapping):
        return dict(value)
    return None


def _item(values: Any, index: int) -> Any:
    return values[index]


def _first_segment_position(segments: Any, field: str) -> int:
    return int(_get(segments[0], field, 0)) if segments else 0


def _last_segment_position(segments: Any, field: str) -> int:
    return int(_get(segments[-1], field, 0)) if segments else 0
