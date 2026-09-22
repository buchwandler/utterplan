from __future__ import annotations

from dataclasses import replace

from .hashing import UNIT_HASH_SCHEMA, semantic_hash, unit_hash_payload
from .model import Marker, PlanSegment, PlanUnit


def make_units(
    segments: tuple[PlanSegment, ...],
    markers: tuple[Marker, ...],
    tokens: tuple[object, ...],
    kind: str,
) -> tuple[PlanUnit, ...]:
    if not segments:
        return ()
    groups: list[list[PlanSegment]] = []
    current: list[PlanSegment] = []
    current_key: tuple[int, int] | None = None
    closed: set[tuple[int, int]] = set()
    for segment in segments:
        key = (segment.paragraph, segment.sentence if kind == "sentence" else -1)
        if current and key != current_key:
            groups.append(current)
            if current_key is not None:
                closed.add(current_key)
            current = []
        if key in closed:
            raise ValueError(f"non-contiguous unit key {key}")
        current.append(segment)
        current_key = key
    if current:
        groups.append(current)

    units: list[PlanUnit] = []
    for index, group in enumerate(groups):
        start, end = group[0].spoken_start, group[-1].spoken_end
        marker_ids = tuple(
            marker.id
            for marker in markers
            if _marker_belongs(marker.spoken_position, groups, index)
        )
        marker_values = tuple(marker for marker in markers if marker.id in marker_ids)
        provisional = PlanUnit(
            f"unit-{index:04d}",
            index,
            kind,
            start,
            end,
            tuple(segment.id for segment in group),
            marker_ids,
        )
        units.append(
            replace(
                provisional,
                content_hash=semantic_hash(
                    unit_hash_payload(_UnitView(group, marker_ids, marker_values, tokens))
                ),
                content_hash_schema=UNIT_HASH_SCHEMA,
            )
        )
    return tuple(units)


def _marker_belongs(position: int, groups: list[list[PlanSegment]], index: int) -> bool:
    group = groups[index]
    start = group[0].spoken_start
    end = group[-1].spoken_end
    if index < len(groups) - 1 and end <= position <= groups[index + 1][0].spoken_start:
        return False
    if index > 0 and groups[index - 1][-1].spoken_end <= position <= start:
        return True
    return start <= position < end or (index == len(groups) - 1 and position == end)


class _UnitView:
    def __init__(
        self,
        segments: list[PlanSegment],
        marker_ids: tuple[str, ...],
        marker_values: tuple[Marker, ...],
        tokens: tuple[object, ...],
    ) -> None:
        self.segments = tuple(segments)
        self.marker_ids = marker_ids
        self.marker_values = marker_values
        self.tokens = tokens
