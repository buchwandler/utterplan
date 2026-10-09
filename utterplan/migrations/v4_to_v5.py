from __future__ import annotations

import math
from collections.abc import Mapping
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from ..exceptions import PlanMigrationError
from ..hashing import FLOW_HASH_SCHEMA, flow_plan_id, flow_unit_hash
from .registry import register_migration

_FORMAT = "utterplan"
_PAUSE_STRENGTHS = frozenset({"none", "x-weak", "weak", "medium", "strong", "x-strong"})
_AUTOMATIC_PAUSES = {
    "weak": (1, "weak"),
    "voice_change": (2, "voice_change"),
    "parenthetical": (3, "parenthetical"),
    "clause": (4, "clause"),
    "clausal_comma": (4, "clause"),
    "sentence": (5, "sentence"),
    "paragraph": (6, "paragraph"),
}


def _error(message: str, path: str, *, code: str = "migration.v4-invalid") -> PlanMigrationError:
    return PlanMigrationError(message, code=code, path=path)


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _error("expected an object", path)
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise _error("expected an array", path)
    return value


def _required_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise _error("expected a non-empty string", path)
    return value


def _normalize_time(seconds: int | float) -> str:
    try:
        milliseconds = Decimal(str(seconds)) * 1000
    except (InvalidOperation, ValueError) as exc:
        raise _error("explicit pause duration cannot be canonicalized", "$.segments") from exc
    if not milliseconds.is_finite() or milliseconds <= 0:
        raise _error("explicit timed pause must be greater than zero", "$.segments")
    value = format(milliseconds.normalize(), "f")
    return f"{value}ms"


def _explicit_pause(
    event: Mapping[str, Any], aggregate_seconds: int | float | None, path: str
) -> str | dict[str, str]:
    attrs = event.get("attrs", {})
    if not isinstance(attrs, Mapping):
        raise _error("explicit boundary attrs must be an object", f"{path}.attrs")
    origin = event.get("origin")
    pause_origin = attrs.get("pause_origin")
    if (
        origin != "ssmd"
        or not isinstance(pause_origin, str)
        or pause_origin not in {"explicit", "none"}
    ):
        raise _error(
            "explicit pause lacks authored SSMD provenance; recompile from source",
            path,
            code="migration.pause-ambiguous",
        )
    strength = event.get("strength") or attrs.get("strength")
    if strength is not None and not isinstance(strength, str):
        raise _error("authored pause strength must be a string", f"{path}.strength")
    if pause_origin == "none" or strength == "none":
        return "none"
    time = attrs.get("time")
    if time is not None:
        if not isinstance(time, str) or not time.strip():
            raise _error("authored timed pause has an invalid time token", f"{path}.attrs.time")
        return {"type": "timed", "time": time}
    if strength is not None:
        if strength not in _PAUSE_STRENGTHS:
            raise _error(
                f"unsupported authored pause strength {strength!r}",
                f"{path}.strength",
                code="migration.pause-ambiguous",
            )
        return strength
    duration = event.get("seconds")
    if duration is None:
        duration = aggregate_seconds
    if type(duration) not in {int, float}:
        raise _error(
            "authored pause has no recoverable strength or attributable duration; recompile from source",
            path,
            code="migration.pause-ambiguous",
        )
    return {"type": "timed", "time": _normalize_time(cast(int | float, duration))}


def _pause_intent(
    value: Any,
    boundaries_by_id: Mapping[str, Mapping[str, Any]],
    path: str,
    expected_position: int,
) -> str | dict[str, str] | None:
    if value is None:
        return None
    pause = _mapping(value, path)
    seconds = pause.get("seconds")
    if type(seconds) not in {int, float}:
        raise _error("pause seconds must be a non-negative number", f"{path}.seconds")
    seconds_value = cast(int | float, seconds)
    if not math.isfinite(seconds_value) or seconds_value < 0:
        raise _error("pause seconds must be a non-negative number", f"{path}.seconds")
    event_ids = _list(pause.get("events"), f"{path}.events")
    if any(not isinstance(item, str) for item in event_ids):
        raise _error("pause event IDs must be strings", f"{path}.events")
    if not event_ids:
        if seconds_value == 0:
            return None
        raise _error(
            "aggregate pause duration has no event provenance; recompile from source",
            path,
            code="migration.pause-ambiguous",
        )

    authored: list[str | dict[str, str]] = []
    automatic: list[tuple[int, str, str]] = []
    for event_index, event_id in enumerate(event_ids):
        event = boundaries_by_id.get(event_id)
        event_path = f"{path}.events[{event_index}]"
        if event is None:
            raise _error(f"pause references unknown boundary {event_id!r}", event_path)
        event_position = event.get("position")
        if type(event_position) is not int or event_position != expected_position:
            raise _error(
                "pause boundary is not located at its owning segment edge",
                event_path,
                code="migration.pause-ambiguous",
            )
        kind = event.get("kind")
        attrs = event.get("attrs", {})
        if isinstance(attrs, Mapping) and attrs.get("structural_only"):
            continue
        if kind == "explicit":
            attributed_seconds = seconds_value if len(event_ids) == 1 else None
            authored.append(_explicit_pause(event, attributed_seconds, f"$.boundaries[{event_id}]"))
            continue
        if not isinstance(kind, str) or kind not in _AUTOMATIC_PAUSES:
            raise _error(
                f"cannot recover pause intent from boundary kind {kind!r}",
                event_path,
                code="migration.pause-ambiguous",
            )
        priority, pause_type = _AUTOMATIC_PAUSES[kind]
        automatic.append((priority, pause_type, event_id))

    if authored:
        if len(authored) > 1:
            raise _error(
                "multiple authored pauses share one segment edge; recompile from source",
                path,
                code="migration.pause-ambiguous",
            )
        return authored[0]
    if not automatic:
        return None
    _priority, pause_type, _event_id = max(automatic, key=lambda item: (item[0], item[2]))
    return pause_type


def _token_views(
    segment: Mapping[str, Any],
    tokens: list[Any],
    segment_index: int,
    used_tokens: set[int],
    spoken: str,
) -> list[dict[str, Any]]:
    path = f"$.segments[{segment_index}]"
    start, end = segment.get("spoken_start"), segment.get("spoken_end")
    text, language = segment.get("text"), segment.get("language")
    if type(start) is not int or type(end) is not int or end < start:
        raise _error("segment spoken range is invalid", f"{path}.spoken_start")
    if not isinstance(text, str):
        raise _error("segment text must be a string", f"{path}.text")
    if start < 0 or end > len(spoken) or spoken[start:end] != text:
        raise _error(
            "segment spoken range cannot be verified against document text",
            f"{path}.spoken_start",
            code="migration.segment-coordinate-ambiguous",
        )
    if not isinstance(language, str) or not language:
        raise _error("segment language must be a non-empty string", f"{path}.language")

    indices = _list(segment.get("token_indices"), f"{path}.token_indices")
    if any(type(index) is not int for index in indices):
        raise _error("segment token indices must be integers", f"{path}.token_indices")
    if len(indices) != len(set(indices)):
        raise _error("segment repeats a token index", f"{path}.token_indices")
    result: list[dict[str, Any]] = []
    previous_end = 0
    for token_index in indices:
        if type(token_index) is not int or not 0 <= token_index < len(tokens):
            raise _error("segment references an unknown token", f"{path}.token_indices")
        if token_index in used_tokens:
            raise _error("token is referenced by more than one segment", f"{path}.token_indices")
        used_tokens.add(token_index)
        token_path = f"$.tokens[{token_index}]"
        token = _mapping(tokens[token_index], token_path)
        token_start, token_end = token.get("spoken_start"), token.get("spoken_end")
        surface = token.get("text")
        if type(token_start) is not int or type(token_end) is not int or token_end <= token_start:
            raise _error("token spoken range is invalid", f"{token_path}.spoken_start")
        if not isinstance(surface, str) or not surface:
            raise _error("token surface must be a non-empty string", f"{token_path}.text")
        local_start, local_end = token_start - start, token_end - start
        if local_start < 0 or local_end > len(text) or text[local_start:local_end] != surface:
            raise _error(
                "token span cannot be verified against its owning segment text",
                token_path,
                code="migration.token-coordinate-ambiguous",
            )
        token_language = token.get("language")
        if token_language is not None and token_language != language:
            raise _error(
                "token language differs from owning segment language and cannot be represented",
                f"{token_path}.language",
                code="migration.token-language-unsupported",
            )
        if local_start < previous_end:
            raise _error("segment token spans overlap or are unordered", f"{path}.token_indices")
        previous_end = local_end
        view: dict[str, Any] = {"start": local_start, "end": local_end}
        for field in ("lemma", "pos", "tag", "morph"):
            value = token.get(field)
            if value is not None:
                if not isinstance(value, str):
                    raise _error(f"token {field} must be a string or null", f"{token_path}.{field}")
                view[field] = value
        result.append(view)
    return result


def _locate_segment(
    position: int,
    segments: list[Mapping[str, Any]],
    *,
    prefer_start: bool = False,
) -> Mapping[str, Any] | None:
    candidates: list[tuple[tuple[int, int, int], Mapping[str, Any]]] = []
    for index, segment in enumerate(segments):
        start_value, end_value = segment.get("spoken_start"), segment.get("spoken_end")
        if type(start_value) is not int or type(end_value) is not int:
            continue
        start, end = cast(int, start_value), cast(int, end_value)
        if prefer_start and position == start:
            candidates.append(((0, end - start, index), segment))
        elif not prefer_start and position == end:
            candidates.append(((0, -end, index), segment))
        elif start < position < end:
            candidates.append(((1, end - start, index), segment))
        elif position == (end if prefer_start else start):
            candidates.append(((2, end - start, index), segment))
    if candidates:
        return min(candidates, key=lambda item: item[0])[1]
    return None


def _heading_level(event: Mapping[str, Any], path: str) -> int:
    attrs = event.get("attrs", {})
    if not isinstance(attrs, Mapping):
        raise _error("heading boundary attrs must be an object", f"{path}.attrs")
    value = attrs.get("level")
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if type(value) is not int or value < 1:
        raise _error("heading boundary requires a positive level", f"{path}.attrs.level")
    return value


def _document_info(source: Mapping[str, Any]) -> dict[str, Any]:
    metadata_value = source.get("document_metadata", {})
    metadata = metadata_value if isinstance(metadata_value, Mapping) else {}
    header_value = metadata.get("header", {})
    header = header_value if isinstance(header_value, Mapping) else {}
    semantics: dict[str, Any] = {}
    for key in ("voice_bindings", "prosody_transitions", "requires"):
        value = metadata.get(key, header.get(key))
        if value is not None:
            semantics[key] = deepcopy(value)
    for values in (metadata, header):
        for key, value in values.items():
            if isinstance(key, str) and key.startswith("x-"):
                semantics[key] = deepcopy(value)
    document: dict[str, Any] = {"semantics": semantics}
    source_value = source.get("source", {})
    source_format = source_value.get("format") if isinstance(source_value, Mapping) else None
    for key, value in (
        ("format", source_format),
        ("ssmd_version", metadata.get("ssmd_version", header.get("ssmd_version"))),
        ("title", metadata.get("title", header.get("title"))),
    ):
        if isinstance(value, str) and value:
            document[key] = value
    return document


def _linguistic_info(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    languages: dict[str, str] = {}
    for index, item in enumerate(_list(source.get("languages", []), "$.languages")):
        language_record = _mapping(item, f"$.languages[{index}]")
        identifier, tag = language_record.get("id"), language_record.get("language")
        if not isinstance(identifier, str) or not isinstance(tag, str) or not tag:
            raise _error("language run mapping is invalid", f"$.languages[{index}]")
        if identifier in languages:
            raise _error("duplicate language ID", f"$.languages[{index}].id")
        languages[identifier] = tag

    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for index, item in enumerate(_list(source.get("linguistic_runs", []), "$.linguistic_runs")):
        path = f"$.linguistic_runs[{index}]"
        run = _mapping(item, path)
        run_id, provider = run.get("language_run_id"), run.get("provider")
        language = languages.get(run_id) if isinstance(run_id, str) else None
        if language is None:
            raise _error(
                "linguistic run references an unknown language run", f"{path}.language_run_id"
            )
        if not isinstance(provider, str) or provider not in {"spacy", "fallback", "unknown"}:
            raise _error("linguistic provider is invalid", f"{path}.provider")
        entry: dict[str, Any] = {"language": language, "provider": provider}
        for field in ("model", "provider_version", "model_version"):
            value = run.get(field)
            if value is not None:
                if not isinstance(value, str):
                    raise _error(f"{field} must be a string or null", f"{path}.{field}")
                entry[field] = value
        identity = tuple(
            entry.get(field)
            for field in ("language", "provider", "model", "provider_version", "model_version")
        )
        if identity not in seen:
            result.append(entry)
            seen.add(identity)
    return result


def migrate_v4_to_v5(data: Mapping[str, Any]) -> dict[str, Any]:
    """Purely project serialized v4 semantics into the compact v5 executable flow."""
    if not isinstance(data, Mapping) or data.get("format") != _FORMAT:
        raise _error("expected an UtterPlan semantic mapping", "$")
    if data.get("schema_version") != 4:
        raise PlanMigrationError(
            "v4_to_v5 requires schema version 4",
            code="migration.source-version-invalid",
            path="$.schema_version",
        )
    source = deepcopy(dict(data))
    config = _mapping(source.get("config"), "$.config")
    language = _required_string(config.get("language"), "$.config.language")
    unit_kind = config.get("unit")
    if not isinstance(unit_kind, str) or unit_kind not in {"sentence", "paragraph"}:
        raise _error("unit must be sentence or paragraph", "$.config.unit")
    texts = _mapping(source.get("texts"), "$.texts")
    spoken = texts.get("spoken")
    if not isinstance(spoken, str):
        raise _error("spoken text must be a string", "$.texts.spoken")

    tokens = _list(source.get("tokens"), "$.tokens")
    boundaries = _list(source.get("boundaries"), "$.boundaries")
    boundaries_by_id: dict[str, Mapping[str, Any]] = {}
    for index, item in enumerate(boundaries):
        path = f"$.boundaries[{index}]"
        event = _mapping(item, path)
        event_id = event.get("id")
        if not isinstance(event_id, str) or not event_id:
            raise _error("boundary ID must be a non-empty string", f"{path}.id")
        if event_id in boundaries_by_id:
            raise _error("duplicate boundary ID", f"{path}.id")
        boundaries_by_id[event_id] = event

    segments_value = _list(source.get("segments"), "$.segments")
    segments: list[Mapping[str, Any]] = []
    segments_by_id: dict[str, Mapping[str, Any]] = {}
    for index, item in enumerate(segments_value):
        segment = _mapping(item, f"$.segments[{index}]")
        segment_id = segment.get("id")
        if not isinstance(segment_id, str) or not segment_id:
            raise _error("segment ID must be a non-empty string", f"$.segments[{index}].id")
        if segment_id in segments_by_id:
            raise _error("duplicate segment ID", f"$.segments[{index}].id")
        segments.append(segment)
        segments_by_id[segment_id] = segment

    markers_value = _list(source.get("markers", []), "$.markers")
    marker_owners: dict[str, int] = {}
    for unit_index, item in enumerate(_list(source.get("units"), "$.units")):
        unit = _mapping(item, f"$.units[{unit_index}]")
        for marker_id in _list(unit.get("marker_ids", []), f"$.units[{unit_index}].marker_ids"):
            if not isinstance(marker_id, str):
                raise _error("marker IDs must be strings", f"$.units[{unit_index}].marker_ids")
            if marker_id in marker_owners:
                raise _error(
                    "marker is referenced by multiple units", f"$.units[{unit_index}].marker_ids"
                )
            marker_owners[marker_id] = unit_index

    markers_by_segment: dict[str, list[tuple[int, int, str]]] = {}
    marker_by_id: dict[str, Mapping[str, Any]] = {}
    for marker_index, item in enumerate(markers_value):
        path = f"$.markers[{marker_index}]"
        marker = _mapping(item, path)
        marker_id, name, position = (
            marker.get("id"),
            marker.get("name"),
            marker.get("spoken_position"),
        )
        if not isinstance(marker_id, str) or not marker_id or marker_id in marker_by_id:
            raise _error("marker ID must be unique and non-empty", f"{path}.id")
        if not isinstance(name, str) or not name:
            raise _error("marker name must be a non-empty string", f"{path}.name")
        if type(position) is not int or not 0 <= position <= len(spoken):
            raise _error(
                "marker position must be a non-negative integer", f"{path}.spoken_position"
            )
        position_value = cast(int, position)
        marker_by_id[marker_id] = marker
        candidates = segments
        owner = marker_owners.get(marker_id)
        if owner is not None:
            units = _list(source.get("units"), "$.units")
            owner_unit = _mapping(units[owner], f"$.units[{owner}]")
            owner_ids = _list(owner_unit.get("segment_ids"), f"$.units[{owner}].segment_ids")
            candidates = [segments_by_id[value] for value in owner_ids if value in segments_by_id]
        chosen = _locate_segment(position_value, candidates)
        if chosen is None and candidates:

            def marker_distance(segment: Mapping[str, Any], reference: int = position_value) -> int:
                start_value = segment.get("spoken_start")
                end_value = segment.get("spoken_end")
                start = cast(int, start_value) if type(start_value) is int else reference
                end = cast(int, end_value) if type(end_value) is int else reference
                return min(abs(reference - start), abs(reference - end))

            chosen = min(candidates, key=marker_distance)
        if chosen is None:
            raise _error(
                "marker has no owning speech segment", path, code="migration.marker-unlocalized"
            )
        segment_id = chosen.get("id")
        markers_by_segment.setdefault(str(segment_id), []).append(
            (position_value, marker_index, name)
        )
    unknown_marker_refs = set(marker_owners) - set(marker_by_id)
    if unknown_marker_refs:
        raise _error(
            f"unit references unknown marker IDs {sorted(unknown_marker_refs)}",
            "$.units",
        )

    headings_by_segment: dict[str, int] = {}
    for boundary_index, event in enumerate(boundaries):
        if event.get("kind") != "heading":
            continue
        position = event.get("position")
        if type(position) is not int or not 0 <= position <= len(spoken):
            raise _error(
                "heading position must be a non-negative integer",
                f"$.boundaries[{boundary_index}].position",
            )
        heading_attrs = event.get("attrs", {})
        prefer_start = (
            isinstance(heading_attrs, Mapping) and heading_attrs.get("anchor") == "before"
        )
        heading_segment = _locate_segment(position, segments, prefer_start=prefer_start)
        if heading_segment is None:
            raise _error(
                "heading has no owning speech segment",
                f"$.boundaries[{boundary_index}]",
                code="migration.heading-unlocalized",
            )
        segment_id = str(heading_segment.get("id"))
        level = _heading_level(event, f"$.boundaries[{boundary_index}]")
        previous = headings_by_segment.get(segment_id)
        if previous is not None and previous != level:
            raise _error(
                "multiple heading levels map to one segment", f"$.boundaries[{boundary_index}]"
            )
        headings_by_segment[segment_id] = level

    units_value = _list(source.get("units"), "$.units")
    used_segment_ids: set[str] = set()
    used_tokens: set[int] = set()
    flow: list[dict[str, Any]] = []
    for unit_index, item in enumerate(units_value):
        path = f"$.units[{unit_index}]"
        unit = _mapping(item, path)
        segment_ids = _list(unit.get("segment_ids"), f"{path}.segment_ids")
        flow_segments: list[dict[str, Any]] = []
        for segment_id in segment_ids:
            if not isinstance(segment_id, str) or segment_id not in segments_by_id:
                raise _error("unit references an unknown segment", f"{path}.segment_ids")
            if segment_id in used_segment_ids:
                raise _error("segment is referenced by multiple units", f"{path}.segment_ids")
            used_segment_ids.add(segment_id)
            segment = segments_by_id[segment_id]
            segment_index = next(
                index for index, candidate in enumerate(segments) if candidate is segment
            )
            directives = segment.get("directives", {})
            if not isinstance(directives, Mapping):
                raise _error(
                    "segment directives must be an object",
                    f"$.segments[{segment_index}].directives",
                )
            flow_segment: dict[str, Any] = {
                "text": _required_string(segment.get("text"), f"$.segments[{segment_index}].text")
                if segment.get("text") != ""
                else "",
                "language": _required_string(
                    segment.get("language"), f"$.segments[{segment_index}].language"
                ),
                "directives": deepcopy(dict(directives)),
                "tokens": _token_views(segment, tokens, segment_index, used_tokens, spoken),
                "markers": [
                    name
                    for _position, _marker_index, name in sorted(
                        markers_by_segment.get(segment_id, [])
                    )
                ],
            }
            for edge in ("pause_before", "pause_after"):
                pause = _pause_intent(
                    segment.get(edge),
                    boundaries_by_id,
                    f"$.segments[{segment_index}].{edge}",
                    segment["spoken_start"] if edge == "pause_before" else segment["spoken_end"],
                )
                if pause is not None:
                    flow_segment[edge] = pause
            heading = headings_by_segment.get(segment_id)
            if heading is not None:
                flow_segment["heading"] = heading
            flow_segments.append(flow_segment)
        flow.append({"segments": flow_segments, "hash": flow_unit_hash(flow_segments)})
    if used_segment_ids != set(segments_by_id):
        raise _error("v4 units do not own every segment exactly once", "$.units")
    if used_tokens != set(range(len(tokens))):
        raise _error(
            "v4 tokens are not all owned by verified segment-local spans",
            "$.tokens",
            code="migration.token-coordinate-ambiguous",
        )

    result: dict[str, Any] = {
        "format": _FORMAT,
        "schema_version": 5,
        "plan_id": "",
        "language": language,
        "unit": unit_kind,
        "hash_schema": FLOW_HASH_SCHEMA,
        "document": _document_info(source),
        "linguistics": _linguistic_info(source),
        "flow": flow,
    }
    result["plan_id"] = flow_plan_id(result)
    return result


register_migration(4, migrate_v4_to_v5)

__all__ = ["migrate_v4_to_v5"]
