from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

from .config import PauseConfig
from .model import BoundaryEvent, PlanSegment, ResolvedPause

_AUTOMATIC_AUTO_MODE_KINDS = frozenset(
    {
        "clausal_comma",
        "parenthetical",
        "voice_change",
    }
)


def boundary_is_active(event: BoundaryEvent, config: PauseConfig) -> bool:
    if event.attrs.get("structural_only"):
        return False
    automatic = bool(event.attrs.get("automatic")) or (
        event.kind in {"paragraph", "sentence"}
        and event.seconds is None
        and event.origin in {"plain", "ssmd", "planner"}
    )
    if automatic and not config.enabled:
        return False
    return not (automatic and config.mode != "auto" and event.kind in _AUTOMATIC_AUTO_MODE_KINDS)


def resolve_pauses(
    segments: list[PlanSegment], boundaries: list[BoundaryEvent], config: PauseConfig
) -> list[PlanSegment]:
    """Resolve semantic pause events without renderer-specific policy."""
    events_after: dict[int, list[BoundaryEvent]] = defaultdict(list)
    events_before: dict[int, list[BoundaryEvent]] = defaultdict(list)
    for event in boundaries:
        if not boundary_is_active(event, config):
            continue
        duration = event.seconds
        if duration is None:
            duration = {
                "weak": config.weak,
                "clause": config.clause,
                "clausal_comma": config.clause,
                "sentence": config.sentence,
                "paragraph": config.paragraph,
                "parenthetical": config.parenthetical,
                "voice_change": config.voice_change,
            }.get(event.kind, config.weak)
        resolved = replace(event, seconds=max(0.0, float(duration or 0.0)))
        anchor = str(event.attrs.get("anchor", "after"))
        (events_before if anchor == "before" else events_after)[event.position].append(resolved)
    for index, segment in enumerate(segments):
        before = events_before.get(segment.spoken_start, [])
        after = events_after.get(segment.spoken_end, [])
        segments[index] = replace(segment, pause_before=_pause(before), pause_after=_pause(after))
    return segments


def _pause(events: list[BoundaryEvent]) -> ResolvedPause:
    if not events:
        return ResolvedPause()
    winner = max(events, key=lambda event: (float(event.seconds or 0), event.id))
    return ResolvedPause(
        float(winner.seconds or 0),
        tuple(event.id for event in sorted(events, key=lambda event: event.id)),
    )
