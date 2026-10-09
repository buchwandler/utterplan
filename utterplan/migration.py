from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .exceptions import (
    MigrationPathError,
    PlanFormatError,
    PlanMigrationError,
    UnsupportedSchemaError,
)
from .migrations.registry import MigrationFn, migration_registry
from .versioning import CURRENT_SCHEMA_VERSION, FORMAT


@dataclass(frozen=True, slots=True)
class PlanEnvelope:
    schema_version: int
    plan_id: str | None


@dataclass(frozen=True, slots=True)
class MigrationStep:
    source_version: int
    target_version: int


@dataclass(frozen=True, slots=True)
class MigrationResult:
    data: Mapping[str, Any]
    source_version: int
    target_version: int
    steps: tuple[MigrationStep, ...]
    source_plan_id: str | None
    target_plan_id: str | None

    @property
    def changed(self) -> bool:
        return self.source_version != self.target_version


def inspect_envelope(data: Any) -> PlanEnvelope:
    if not isinstance(data, Mapping):
        raise PlanFormatError("plan must be an object", code="json.type")
    if data.get("format") != FORMAT:
        raise PlanFormatError("format must be 'utterplan'", code="format.invalid", path="$.format")
    if "schema_version" not in data:
        raise PlanMigrationError(
            "schema_version is required to route the plan",
            code="migration.source-version-missing",
            path="$.schema_version",
        )
    version = data["schema_version"]
    if type(version) is not int:
        raise PlanMigrationError(
            "schema_version must be an integer",
            code="migration.source-version-invalid",
            path="$.schema_version",
        )
    plan_id = data.get("plan_id")
    return PlanEnvelope(version, plan_id if isinstance(plan_id, str) else None)


def _apply_migration_chain(
    data: Mapping[str, Any],
    *,
    target_version: int,
    registry: Mapping[int, MigrationFn],
) -> tuple[dict[str, Any], tuple[MigrationStep, ...]]:
    working = deepcopy(dict(data))
    source = inspect_envelope(working).schema_version
    if target_version < source:
        raise PlanMigrationError(
            f"downgrade from schema {source} to {target_version} is not supported",
            code="migration.downgrade",
            path="$.schema_version",
        )

    steps: list[MigrationStep] = []
    while working["schema_version"] < target_version:
        source_version = working["schema_version"]
        migration = registry.get(source_version)
        if migration is None:
            raise MigrationPathError(
                f"no migration registered from schema {source_version} to {source_version + 1}",
                code="migration.no-path",
                path="$.schema_version",
            )
        before = deepcopy(working)
        try:
            candidate = migration(working)
        except PlanMigrationError:
            raise
        except Exception as exc:
            raise PlanMigrationError(
                f"migration step {source_version} failed: {exc}",
                code="migration.step-invalid",
            ) from exc
        if working != before:
            raise PlanMigrationError(
                f"migration step {source_version} mutated its input",
                code="migration.step-invalid",
            )
        if not isinstance(candidate, Mapping):
            raise PlanMigrationError(
                f"migration step {source_version} returned a non-mapping",
                code="migration.result-invalid",
            )
        working = dict(candidate)
        expected = source_version + 1
        if type(working.get("schema_version")) is not int or working["schema_version"] != expected:
            raise PlanMigrationError(
                f"migration step {source_version} must produce schema {expected}",
                code="migration.step-invalid",
                path="$.schema_version",
            )
        steps.append(MigrationStep(source_version, expected))
        if len(steps) > target_version - source:
            raise PlanMigrationError(
                "migration chain did not advance", code="migration.step-invalid"
            )
    return working, tuple(steps)


def _record_provenance(
    data: dict[str, Any],
    *,
    source_version: int,
    source_plan_id: str | None,
    steps: tuple[MigrationStep, ...],
) -> None:
    producer = data.get("producer")
    if not isinstance(producer, Mapping):
        return
    producer_copy = deepcopy(dict(producer))
    previous = producer_copy.get("migration")
    if isinstance(previous, Mapping):
        original_schema = previous.get("original_schema_version", source_version)
        original_plan_id = previous.get("original_plan_id", source_plan_id)
        previous_steps = previous.get("steps", [])
    else:
        original_schema = source_version
        original_plan_id = source_plan_id
        previous_steps = []
    if not isinstance(previous_steps, list):
        previous_steps = []
    producer_copy["migration"] = {
        "original_schema_version": original_schema,
        "original_plan_id": original_plan_id,
        "steps": [
            *deepcopy(previous_steps),
            *[{"from": step.source_version, "to": step.target_version} for step in steps],
        ],
    }
    data["producer"] = producer_copy


def migrate_plan_data(
    data: Mapping[str, Any],
    *,
    target_version: int | None = None,
) -> MigrationResult:
    original = deepcopy(dict(data)) if isinstance(data, Mapping) else data
    envelope = inspect_envelope(original)
    target = CURRENT_SCHEMA_VERSION if target_version is None else target_version
    if type(target) is not int:
        raise PlanMigrationError(
            "target schema version must be an integer", code="migration.target-invalid"
        )
    if envelope.schema_version > CURRENT_SCHEMA_VERSION:
        raise UnsupportedSchemaError(envelope.schema_version)
    if target > CURRENT_SCHEMA_VERSION:
        raise UnsupportedSchemaError(target)
    if target < envelope.schema_version:
        raise PlanMigrationError(
            f"downgrade from schema {envelope.schema_version} to {target} is not supported",
            code="migration.downgrade",
            path="$.schema_version",
        )

    working, steps = _apply_migration_chain(
        original,
        target_version=target,
        registry=migration_registry(),
    )
    if steps and target != 5:
        _record_provenance(
            working,
            source_version=envelope.schema_version,
            source_plan_id=envelope.plan_id,
            steps=steps,
        )
    result_envelope = inspect_envelope(working)
    return MigrationResult(
        data=working,
        source_version=envelope.schema_version,
        target_version=result_envelope.schema_version,
        steps=steps,
        source_plan_id=envelope.plan_id,
        target_plan_id=result_envelope.plan_id,
    )


__all__ = [
    "MigrationResult",
    "MigrationStep",
    "PlanEnvelope",
    "_apply_migration_chain",
    "inspect_envelope",
    "migrate_plan_data",
]
