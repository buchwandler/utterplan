from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ..exceptions import PlanMigrationError
from ..hashing import UNIT_HASH_SCHEMA, semantic_hash
from .registry import register_migration


def _error(message: str, code: str = "migration.v1-invalid") -> PlanMigrationError:
    return PlanMigrationError(message, code=code)


def _legacy_tokens_by_language(
    data: Mapping[str, Any],
) -> list[dict[str, Any]]:
    languages = data.get("languages")
    tokens = data.get("tokens")
    if not isinstance(languages, list) or not isinstance(tokens, list):
        raise _error("v1 languages and tokens must be arrays")
    text = data.get("texts", {}).get("spoken") if isinstance(data.get("texts"), Mapping) else None
    if not isinstance(text, str):
        raise _error("v1 spoken text is required")

    assignments: list[int | None] = [None] * len(tokens)
    ranges: list[tuple[int, int]] = []
    for language_index, language in enumerate(languages):
        if not isinstance(language, Mapping):
            raise _error("v1 language run must be an object")
        start = language.get("spoken_start")
        end = language.get("spoken_end")
        if type(start) is not int or type(end) is not int or not (0 <= start <= end <= len(text)):
            raise _error("v1 language run range is invalid")
        language_id = language.get("id")
        if not isinstance(language_id, str):
            raise _error("v1 language run id is invalid")
        if ranges and start < ranges[-1][1]:
            raise _error("v1 language runs overlap or are not ordered")
        ranges.append((start, end))
        contained: list[int] = []
        for token_index, token in enumerate(tokens):
            if not isinstance(token, Mapping):
                raise _error("v1 token must be an object")
            token_start = token.get("spoken_start")
            token_end = token.get("spoken_end")
            token_text = token.get("text")
            if (
                type(token_start) is not int
                or type(token_end) is not int
                or not isinstance(token_text, str)
                or not (0 <= token_start <= token_end <= len(text))
                or text[token_start:token_end] != token_text
            ):
                raise _error("v1 token range or text is invalid")
            overlaps = token_start < end and token_end > start
            contained_by_run = start <= token_start and token_end <= end
            if overlaps and not contained_by_run:
                raise _error("v1 token overlaps a language boundary ambiguously")
            if contained_by_run:
                if assignments[token_index] is not None:
                    raise _error("v1 token belongs to multiple language runs")
                assignments[token_index] = language_index
                contained.append(token_index)
        if contained and contained != list(range(contained[0], contained[-1] + 1)):
            raise _error("v1 language token range is not contiguous")

    if any(assignment is None for assignment in assignments):
        raise _error("v1 token is not covered by a language run")

    result: list[dict[str, Any]] = []
    for language_index, (_start, _end) in enumerate(ranges):
        indices = [
            index for index, assignment in enumerate(assignments) if assignment == language_index
        ]
        token_start = (
            indices[0]
            if indices
            else next(
                (
                    index
                    for index, assignment in enumerate(assignments)
                    if assignment is not None and assignment > language_index
                ),
                len(tokens),
            )
        )
        token_end = indices[-1] + 1 if indices else token_start
        language = languages[language_index]
        result.append(
            {
                "language_run_id": language["id"],
                "provider": "unknown",
                "model": None,
                "provider_version": None,
                "model_version": None,
                "token_start": token_start,
                "token_end": token_end,
            }
        )
    return result


def _token_semantics(token: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "text": token.get("text"),
        "language": token.get("language"),
        "lemma": token.get("lemma"),
        "pos": token.get("pos"),
        "tag": token.get("tag"),
        "morph": token.get("morph"),
    }


def _unit_hash_payload(
    unit: Mapping[str, Any],
    segments: Mapping[str, Mapping[str, Any]],
    tokens: list[Mapping[str, Any]],
    markers: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    segment_values = [segments[segment_id] for segment_id in unit.get("segment_ids", ())]
    marker_values: list[dict[str, Any]] = []
    for marker_id in unit.get("marker_ids", ()):
        marker = dict(markers[marker_id])
        marker.pop("id", None)
        marker_values.append(marker)
    token_values = [
        _token_semantics(tokens[token_index])
        for segment in segment_values
        for token_index in segment.get("token_indices", ())
    ]
    return {
        "hash_schema": UNIT_HASH_SCHEMA,
        "segments": [
            {
                "text": segment.get("text"),
                "language": segment.get("language"),
                "directives": segment.get("directives", {}),
                "pause_before": segment.get("pause_before", {}),
                "pause_after": segment.get("pause_after", {}),
            }
            for segment in segment_values
        ],
        "markers": marker_values,
        "tokens": token_values,
    }


def migrate_v1_to_v2(data: Mapping[str, Any]) -> Mapping[str, Any]:
    if data.get("schema_version") != 1:
        raise _error("v1_to_v2 requires schema version 1", "migration.source-version-invalid")
    result = deepcopy(dict(data))
    linguistic_runs = _legacy_tokens_by_language(result)
    tokens = result.get("tokens")
    if not isinstance(tokens, list):
        raise _error("v1 tokens must be an array")
    result["tokens"] = [dict(token, morph=None) for token in tokens]
    result["linguistic_runs"] = linguistic_runs

    segments = result.get("segments")
    units = result.get("units")
    markers = result.get("markers")
    if (
        not isinstance(segments, list)
        or not isinstance(units, list)
        or not isinstance(markers, list)
    ):
        raise _error("v1 segments, units, and markers must be arrays")
    segment_map: dict[str, Mapping[str, Any]] = {}
    for segment in segments:
        if not isinstance(segment, Mapping) or not isinstance(segment.get("id"), str):
            raise _error("v1 segment must have a string id")
        if segment["id"] in segment_map:
            raise _error("v1 segment ids must be unique")
        segment_map[segment["id"]] = segment
    marker_map: dict[str, Mapping[str, Any]] = {}
    for marker in markers:
        if not isinstance(marker, Mapping) or not isinstance(marker.get("id"), str):
            raise _error("v1 marker must have a string id")
        if marker["id"] in marker_map:
            raise _error("v1 marker ids must be unique")
        marker_map[marker["id"]] = marker
    token_values = [token for token in result["tokens"] if isinstance(token, Mapping)]
    if len(token_values) != len(result["tokens"]):
        raise _error("v1 token must be an object")
    for unit_index, unit in enumerate(units):
        if not isinstance(unit, Mapping):
            raise _error("v1 unit must be an object")
        try:
            payload = _unit_hash_payload(unit, segment_map, token_values, marker_map)
        except (KeyError, IndexError, TypeError) as exc:
            raise _error(f"v1 unit references invalid content: {exc}") from exc
        migrated_unit = dict(unit)
        migrated_unit["content_hash_schema"] = UNIT_HASH_SCHEMA
        migrated_unit["content_hash"] = semantic_hash(payload)
        units[unit_index] = migrated_unit

    result["schema_version"] = 2
    semantic = deepcopy(result)
    for key in ("plan_id", "producer", "diagnostics", "warnings"):
        semantic.pop(key, None)
    config = semantic.get("config")
    if isinstance(config, Mapping):
        semantic["config"] = dict(config)
        semantic["config"].pop("diagnostics", None)
    result["plan_id"] = semantic_hash(semantic)
    return result


register_migration(1, migrate_v1_to_v2)

__all__ = ["migrate_v1_to_v2"]
