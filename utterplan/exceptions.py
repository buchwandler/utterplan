from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .renderability import RenderabilityIssue


class UtterPlanError(Exception):
    """Base exception for UtterPlan."""


class ConfigurationError(UtterPlanError):
    """A public planning configuration value is invalid."""


class PlanFormatError(UtterPlanError):
    """The serialized plan is not structurally valid."""

    def __init__(self, message: str, *, code: str = "plan.invalid", path: str = "$") -> None:
        self.code = code
        self.path = path
        super().__init__(f"{code} at {path}: {message}")


class PlanMigrationError(UtterPlanError):
    """A serialized plan cannot be migrated to the requested schema."""

    def __init__(self, message: str, *, code: str = "migration.invalid", path: str = "$") -> None:
        self.code = code
        self.path = path
        super().__init__(f"{code} at {path}: {message}")


class MigrationPathError(PlanMigrationError):
    """No supported sequential migration path exists."""


class UnsupportedSchemaError(PlanFormatError):
    def __init__(self, version: object) -> None:
        from .versioning import CURRENT_SCHEMA_VERSION

        super().__init__(
            f"Unsupported UtterPlan schema version {version}. "
            f"This version of utterplan supports schema version {CURRENT_SCHEMA_VERSION}.",
            code="schema.unsupported_version",
            path="$.schema_version",
        )


class PlanValidationError(PlanFormatError):
    """The plan has valid JSON shape but invalid planning semantics."""


class PlanningError(UtterPlanError):
    """Planning could not produce a plan."""


class PlanRenderabilityError(PlanningError):
    """Planning found one or more renderer-facing segments without speech intent."""

    code = "plan.not_renderable"

    def __init__(
        self,
        issues: tuple[RenderabilityIssue, ...],
        *,
        mode: str,
    ) -> None:
        self.issues = tuple(issues)
        self.mode = mode
        count = len(self.issues)
        first = self.issues[0] if self.issues else None
        summary = (
            f"Plan is not renderable: {count} renderer segments contain no semantic speech content."
        )
        if first is not None:
            location = (
                f"line {first.line}, column {first.column}, "
                if first.line is not None and first.column is not None
                else ""
            )
            summary += (
                f"\nFirst issue: {location}{first.segment_id}, "
                f"text={first.text!r} ({first.reason})."
            )
        super().__init__(summary)


class LanguagePlanError(PlanningError):
    """Language spans cannot be resolved."""


class TextPreparationError(PlanningError):
    """Written-to-spoken preparation failed."""


class SegmentationError(PlanningError):
    """Segmentation failed."""
