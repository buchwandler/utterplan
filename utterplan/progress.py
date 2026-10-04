"""Typed operational progress events for Utterplan planning."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

ProgressKind = Literal[
    "phase.started",
    "phase.completed",
    "run.started",
    "run.completed",
    "model.started",
    "model.completed",
]

ProgressPhase = Literal[
    "parse",
    "source_analysis",
    "preparation",
    "spoken_analysis",
    "segmentation",
    "finalization",
]


@dataclass(frozen=True, slots=True)
class PlannerProgressEvent:
    """One synchronous, operational event emitted while compiling a plan.

    Events are observations only: they are not stored in planner configuration or
    the resulting semantic plan. Callback handlers should be lightweight. Raising
    from a callback propagates to the caller and can be used to stop planning.
    """

    kind: ProgressKind
    phase: ProgressPhase
    message: str | None = None
    completed: int | None = None
    total: int | None = None
    pass_index: int | None = None
    pass_total: int | None = None
    language: str | None = None
    provider: str | None = None
    model: str | None = None
    char_count: int | None = None
    details: Mapping[str, object] = field(default_factory=dict)


ProgressCallback = Callable[[PlannerProgressEvent], None]


def _notify_progress(
    callback: ProgressCallback | None,
    event: PlannerProgressEvent,
) -> None:
    """Invoke an optional callback synchronously without suppressing exceptions."""
    if callback is not None:
        callback(event)
