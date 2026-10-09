"""Test helpers for assertions against the private normalized compiler model."""

from __future__ import annotations

from typing import Any

from utterplan import PlannerConfig
from utterplan import UtterancePlanner as PublicUtterancePlanner
from utterplan.exceptions import PlanRenderabilityError
from utterplan.progress import ProgressCallback


class CompilerTestPlanner(PublicUtterancePlanner):
    """Expose compiler state only to tests that exercise pre-v5 internals."""

    def plan(
        self,
        text: str,
        *,
        config: PlannerConfig | None = None,
        unit: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> Any:
        attempt, _trace = self._plan(
            text,
            config=config,
            unit=unit,
            trace=False,
            on_progress=on_progress,
        )
        if not attempt.ok:
            raise PlanRenderabilityError(
                attempt.renderability.issues,
                mode=attempt.renderability_mode,
            )
        return object.__getattribute__(attempt.candidate, "_plan")
