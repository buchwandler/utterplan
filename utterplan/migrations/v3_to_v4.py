from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ..exceptions import PlanMigrationError
from ..hashing import UNIT_HASH_SCHEMA, semantic_hash, unit_hash_payload_from_serialized
from .registry import register_migration

_SEMANTIC_KINDS = {
    "clausal_comma": "clause",
    "parenthetical": "parenthetical",
    "sentence": "sentence",
    "paragraph": "paragraph",
}
_CLAUSE_DELIMITERS = frozenset(",;:，；：、—–-")
_CLOSING_PUNCTUATION = frozenset(")]}'\"»”’」』】》〉〕）］｝")


def _error(message: str, *, path: str = "$") -> PlanMigrationError:
    return PlanMigrationError(message, code="migration.v3-invalid", path=path)


def _is_closing_punctuation(character: str) -> bool:
    return character in _CLOSING_PUNCTUATION or unicodedata.category(character) in {"Pe", "Pf"}


def _is_horizontal_whitespace(character: str) -> bool:
    return character == "\t" or unicodedata.category(character) == "Zs"


def _normalize_clause_position(text: str, position: int) -> int:
    """Move a legacy punctuation coordinate after its delimiter and horizontal spacing."""
    if not 0 <= position <= len(text):
        return position

    cursor = position
    has_delimiter = cursor < len(text) and text[cursor] in _CLAUSE_DELIMITERS
    if not has_delimiter and cursor > 0:
        has_delimiter = text[cursor - 1] in _CLAUSE_DELIMITERS
    if not has_delimiter:
        return position

    while cursor < len(text) and text[cursor] in _CLAUSE_DELIMITERS:
        cursor += 1
    while cursor < len(text) and _is_closing_punctuation(text[cursor]):
        cursor += 1
    while cursor < len(text) and _is_horizontal_whitespace(text[cursor]):
        cursor += 1
    return cursor


def _add_candidate(
    groups: dict[tuple[int, str], dict[str, Any]],
    *,
    position: int,
    kind: str,
    origin: str,
    boundary_id: str | None = None,
    original_position: int | None = None,
) -> None:
    group = groups.setdefault((position, kind), {"origins": set(), "sources": set()})
    group["origins"].add(origin)
    if boundary_id is not None and original_position is not None:
        group["sources"].add((boundary_id, original_position))


def _derive_semantic_boundaries(result: Mapping[str, Any], spoken: str) -> list[dict[str, Any]]:
    events = result.get("boundaries")
    if not isinstance(events, list):
        raise _error("v3 boundaries must be an array", path="$.boundaries")

    groups: dict[tuple[int, str], dict[str, Any]] = {}
    for index, event in enumerate(events):
        if not isinstance(event, Mapping):
            continue
        kind = event.get("kind")
        semantic_kind = _SEMANTIC_KINDS.get(kind) if isinstance(kind, str) else None
        if semantic_kind is None:
            continue
        position = event.get("position")
        if type(position) is not int or not 0 <= position <= len(spoken):
            raise _error(
                "semantic source boundary position is outside spoken text",
                path=f"$.boundaries[{index}].position",
            )
        original_position = position
        if semantic_kind == "clause":
            position = _normalize_clause_position(spoken, position)
            if not 0 < position < len(spoken):
                continue
        origin = event.get("origin")
        if not isinstance(origin, str) or not origin:
            origin = "migration"
        boundary_id = event.get("id")
        _add_candidate(
            groups,
            position=position,
            kind=semantic_kind,
            origin=origin,
            boundary_id=boundary_id if isinstance(boundary_id, str) else None,
            original_position=original_position,
        )

    segments = result.get("segments")
    if not isinstance(segments, list):
        raise _error("v3 segments must be an array", path="$.segments")
    for previous, current in zip(segments, segments[1:], strict=False):
        if not isinstance(previous, Mapping) or not isinstance(current, Mapping):
            continue
        position = previous.get("spoken_end")
        previous_paragraph = previous.get("paragraph")
        current_paragraph = current.get("paragraph")
        previous_sentence = previous.get("sentence")
        current_sentence = current.get("sentence")
        kind = None
        if previous_paragraph != current_paragraph:
            kind = "paragraph"
        elif previous_sentence != current_sentence:
            kind = "sentence"
        if kind is not None and type(position) is int and 0 <= position <= len(spoken):
            _add_candidate(
                groups,
                position=position,
                kind=kind,
                origin="planner",
            )

    ordered = sorted(
        groups.items(),
        key=lambda item: (item[0][0], item[0][1], min(item[1]["origins"])),
    )
    semantic: list[dict[str, Any]] = []
    for index, ((position, kind), group) in enumerate(ordered):
        origins = sorted(group["origins"])
        sources = sorted(group["sources"])
        attrs: dict[str, Any] = {}
        if sources:
            attrs["migrated_from_boundary_id"] = sources[0][0]
            attrs["migrated_from_position"] = sources[0][1]
            if len(sources) > 1:
                attrs["migrated_from_boundary_ids"] = [source[0] for source in sources]
                attrs["migrated_from_positions"] = [source[1] for source in sources]
        if len(origins) > 1:
            attrs["origins"] = origins
        semantic.append(
            {
                "id": f"semantic-boundary-{index:06d}",
                "position": position,
                "kind": kind,
                "origin": origins[0],
                "language_run_id": None,
                **({"attrs": attrs} if attrs else {}),
            }
        )
    return semantic


def _semantic_plan_id(result: Mapping[str, Any]) -> str:
    semantic = deepcopy(dict(result))
    for key in ("plan_id", "producer", "diagnostics", "warnings"):
        semantic.pop(key, None)
    config = semantic.get("config")
    if isinstance(config, Mapping):
        semantic["config"] = dict(config)
        semantic["config"].pop("diagnostics", None)
    return semantic_hash(semantic)


def migrate_v3_to_v4(data: Mapping[str, Any]) -> Mapping[str, Any]:
    if data.get("schema_version") != 3:
        raise PlanMigrationError(
            "v3_to_v4 requires schema version 3",
            code="migration.source-version-invalid",
            path="$.schema_version",
        )
    result = deepcopy(dict(data))
    texts = result.get("texts")
    spoken = texts.get("spoken") if isinstance(texts, Mapping) else None
    if not isinstance(spoken, str):
        raise _error("v3 spoken text is required", path="$.texts.spoken")

    semantic_boundaries = _derive_semantic_boundaries(result, spoken)
    result["schema_version"] = 4
    ordered: dict[str, Any] = {}
    inserted = False
    for key, value in result.items():
        if key == "boundaries":
            ordered["semantic_boundaries"] = semantic_boundaries
            inserted = True
        ordered[key] = value
    if not inserted:
        ordered["semantic_boundaries"] = semantic_boundaries
    result = ordered

    units = result.get("units")
    if not isinstance(units, list):
        raise _error("v3 units must be an array", path="$.units")
    for index, unit in enumerate(units):
        if not isinstance(unit, Mapping):
            raise _error("v3 unit must be an object", path=f"$.units[{index}]")
        try:
            payload = unit_hash_payload_from_serialized(unit, result)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise _error(
                f"v3 unit references invalid content: {exc}", path=f"$.units[{index}]"
            ) from exc
        migrated_unit = dict(unit)
        migrated_unit["content_hash_schema"] = UNIT_HASH_SCHEMA
        migrated_unit["content_hash"] = semantic_hash(payload)
        units[index] = migrated_unit

    result["plan_id"] = _semantic_plan_id(result)
    return result


register_migration(3, migrate_v3_to_v4)

__all__ = ["migrate_v3_to_v4"]
