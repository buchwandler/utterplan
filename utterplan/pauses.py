from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Any, cast

from .config import PauseConfig
from .exceptions import PlanningError
from .model import BoundaryEvent, PauseIntent, PlanSegment

_AUTOMATIC_AUTO_MODE_KINDS = frozenset({"clausal_comma", "parenthetical", "voice_change"})
_AUTHORED_STRENGTHS = frozenset({"none", "x-weak", "weak", "medium", "strong", "x-strong"})
_AUTOMATIC_PRIORITY = {
    "weak": 1,
    "voice_change": 2,
    "parenthetical": 3,
    "clause": 4,
    "sentence": 5,
    "paragraph": 6,
}
_AUTOMATIC_KIND_TO_INTENT = {
    "weak": "weak",
    "clause": "clause",
    "clausal_comma": "clause",
    "sentence": "sentence",
    "paragraph": "paragraph",
    "parenthetical": "parenthetical",
    "voice_change": "voice_change",
}


def boundary_is_active(event: BoundaryEvent, config: PauseConfig) -> bool:
    """Apply the existing tts/manual/auto activation policy to a boundary."""
    if event.attrs.get("structural_only"):
        return False
    automatic = bool(event.attrs.get("automatic")) or (
        event.kind in {"paragraph", "sentence"} and event.origin in {"plain", "ssmd", "planner"}
    )
    if automatic and not config.enabled:
        return False
    return not (automatic and config.mode != "auto" and event.kind in _AUTOMATIC_AUTO_MODE_KINDS)


def resolve_pause_intents(
    segments: list[PlanSegment], boundaries: list[BoundaryEvent], config: PauseConfig
) -> list[PlanSegment]:
    """Attach authored or planner-derived semantic intent to segment edges.

    An authored SSMD event always overrides inferred automatic candidates. Multiple
    authored breaks on one edge are rejected rather than silently collapsed.
    """
    events_after: dict[int, list[BoundaryEvent]] = defaultdict(list)
    events_before: dict[int, list[BoundaryEvent]] = defaultdict(list)
    for event in boundaries:
        if not boundary_is_active(event, config):
            continue
        anchor = str(event.attrs.get("anchor", "after"))
        (events_before if anchor == "before" else events_after)[event.position].append(event)

    for index, segment in enumerate(segments):
        before = events_before.get(segment.spoken_start, [])
        after = events_after.get(segment.spoken_end, [])
        segments[index] = replace(
            segment,
            pause_before=_select_intent(before),
            pause_after=_select_intent(after),
        )
    return segments


def _select_intent(events: list[BoundaryEvent]) -> PauseIntent | None:
    if not events:
        return None
    authored = [
        event
        for event in events
        if event.origin == "ssmd"
        and event.kind == "explicit"
        and event.attrs.get("pause_origin") == "explicit"
    ]
    if authored:
        if len(authored) > 1:
            raise PlanningError(
                "multiple authored SSMD breaks at one segment edge are not supported",
            )
        event = authored[0]
        time = event.attrs.get("time")
        if time is not None:
            if not isinstance(time, str) or not time.strip():
                raise PlanningError("authored SSMD break time must be a non-empty token")
            return PauseIntent("timed", time)
        strength = event.strength or event.attrs.get("strength")
        if strength not in _AUTHORED_STRENGTHS:
            raise PlanningError(
                f"authored SSMD break has unsupported strength {strength!r}",
            )
        return PauseIntent(cast(Any, strength))

    automatic: list[tuple[int, str, str]] = []
    for event in events:
        pause_type = _AUTOMATIC_KIND_TO_INTENT.get(event.kind)
        if pause_type is None:
            continue
        automatic.append((_AUTOMATIC_PRIORITY[pause_type], pause_type, event.id))
    if not automatic:
        return None
    _, pause_type, _ = max(automatic, key=lambda item: (item[0], item[2]))
    return PauseIntent(cast(Any, pause_type))
