from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from .model import Diagnostic, UtterancePlan
from .renderability import RenderabilityIssue, RenderabilityReport

PlanningAttemptStatus = Literal["renderable", "repaired", "blocked"]


@dataclass(frozen=True, slots=True)
class PlanDraft:
    """Inspect-only wrapper around a structurally validated semantic candidate.

    A draft deliberately is not an ``UtterancePlan`` and does not expose canonical
    save/load/validation methods. Its read-only semantic attributes forward to the
    contained candidate so inspection code can use ``draft.segments`` and similar
    accessors without mistaking it for synthesis input.
    """

    _plan: UtterancePlan
    renderability: RenderabilityReport

    def __getattr__(self, name: str) -> Any:
        if name in {"to_dict", "to_toml", "save", "validate", "with_identity", "semantic_dict"}:
            raise AttributeError(f"{name} is unavailable on an inspect-only PlanDraft")
        return getattr(object.__getattribute__(self, "_plan"), name)

    def to_plan(self) -> UtterancePlan:
        """Return canonical synthesis input only when the candidate is renderable."""
        if not self.renderability.ok:
            raise ValueError("a blocked planning-attempt draft is not a canonical UtterancePlan")
        return self._plan


@dataclass(frozen=True, slots=True)
class PlanningAttempt:
    """Outcome of compiling semantic planning state before synthesis."""

    status: PlanningAttemptStatus
    candidate: PlanDraft
    renderability: RenderabilityReport
    diagnostics: tuple[Diagnostic, ...]
    repairs: tuple[RenderabilityIssue, ...]
    attempt_id: str
    renderability_mode: Literal["strict", "repair"]

    @property
    def ok(self) -> bool:
        return self.status in {"renderable", "repaired"}

    def to_dict(self) -> dict[str, Any]:
        """Return the planning-attempt artifact mapping, not a canonical plan."""
        from .attempt_serialization import planning_attempt_to_dict

        return planning_attempt_to_dict(self)

    def to_toml(self) -> str:
        """Serialize this attempt using the separate planning-attempt v1 schema."""
        from .attempt_serialization import dumps_planning_attempt

        return dumps_planning_attempt(self)

    @classmethod
    def from_toml(cls, value: object) -> PlanningAttempt:
        """Load one planning-attempt artifact without using canonical plan loading."""
        from .attempt_serialization import loads_planning_attempt

        return loads_planning_attempt(value)

    def save(self, path: str | Path) -> None:
        """Write this attempt artifact as UTF-8 TOML."""
        from .atomic_io import atomic_write_text

        atomic_write_text(path, self.to_toml(), create_parent=True)

    @classmethod
    def load(cls, path: str | Path) -> PlanningAttempt:
        """Load a planning-attempt artifact from a path."""
        return cls.from_toml(Path(path).read_text(encoding="utf-8"))


def planning_attempt_id(
    *,
    status: PlanningAttemptStatus,
    plan: UtterancePlan,
    report: RenderabilityReport,
    renderability_mode: Literal["strict", "repair"],
) -> str:
    """Build a deterministic identifier from semantic candidate and preflight state."""
    payload = {
        "schema": "utterplan.planning-attempt.v1",
        "status": status,
        "candidate": plan.semantic_dict(),
        "renderability": asdict(report),
        "renderability_mode": renderability_mode,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
