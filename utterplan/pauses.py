from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Any, cast

from .boundaries import BoundaryKind, canonicalize_boundary_kinds
from .exceptions import PlanningError
from .model import BoundaryEvent, PauseIntent, PlanSegment

_AUTHORED_STRENGTHS = frozenset({"none", "x-weak", "weak", "medium", "strong", "x-strong"})
_BOUNDARY_KIND_BY_EVENT: dict[str, BoundaryKind] = {
    "clause": "clause",
    "clausal_comma": "clause",
    "sentence": "sentence",
    "paragraph": "paragraph",
    "parenthetical": "parenthetical",
    "voice_change": "voice_change",
}


def boundary_is_materializable(event: BoundaryEvent) -> bool:
    """Return whether a semantic boundary event may participate in the plan."""
    return not bool(event.attrs.get("structural_only"))


def resolve_edge_semantics(
    segments: list[PlanSegment], boundaries: list[BoundaryEvent]
) -> list[PlanSegment]:
    """Attach canonical boundary opportunities and authored pauses independently."""
    events_after: dict[int, list[BoundaryEvent]] = defaultdict(list)
    events_before: dict[int, list[BoundaryEvent]] = defaultdict(list)
    for event in boundaries:
        if not boundary_is_materializable(event):
            continue
        anchor = str(event.attrs.get("anchor", "after"))
        (events_before if anchor == "before" else events_after)[event.position].append(event)

    for index, segment in enumerate(segments):
        before = events_before.get(segment.spoken_start, [])
        after = events_after.get(segment.spoken_end, [])
        segments[index] = replace(
            segment,
            boundary_before=_boundary_kinds(before),
            boundary_after=_boundary_kinds(after),
            pause_before=select_authored_pause(before),
            pause_after=select_authored_pause(after),
        )
    return segments


def _boundary_kinds(events: list[BoundaryEvent]) -> tuple[BoundaryKind, ...]:
    return canonicalize_boundary_kinds(
        kind for event in events if (kind := _BOUNDARY_KIND_BY_EVENT.get(event.kind)) is not None
    )


def select_authored_pause(events: list[BoundaryEvent]) -> PauseIntent | None:
    """Select the sole authored SSMD break at an edge; ignore automatic opportunities."""
    authored = [
        event
        for event in events
        if event.origin == "ssmd"
        and event.kind == "explicit"
        and event.attrs.get("pause_origin") == "explicit"
    ]
    if not authored:
        return None
    if len(authored) > 1:
        raise PlanningError("multiple authored SSMD breaks at one segment edge are not supported")
    event = authored[0]
    time = event.attrs.get("time")
    if time is not None:
        if not isinstance(time, str) or not time.strip():
            raise PlanningError("authored SSMD break time must be a non-empty token")
        return PauseIntent("timed", time)
    strength = event.strength or event.attrs.get("strength")
    if strength not in _AUTHORED_STRENGTHS:
        raise PlanningError(f"authored SSMD break has unsupported strength {strength!r}")
    return PauseIntent(cast(Any, strength))
