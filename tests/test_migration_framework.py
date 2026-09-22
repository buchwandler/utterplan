from __future__ import annotations

import json
from copy import deepcopy

import pytest

from utterplan import PlannerConfig, UtterancePlanner
from utterplan.exceptions import MigrationPathError, PlanMigrationError, UnsupportedSchemaError
from utterplan.migration import (
    MigrationStep,
    _apply_migration_chain,
    migrate_plan_data,
    migrate_plan_json,
)


def _current_data() -> dict[str, object]:
    return UtterancePlanner(PlannerConfig(language="en-us")).plan("Hello.").to_dict()


def _step(target: int):
    def migrate(data):
        result = deepcopy(dict(data))
        result["schema_version"] = target
        result[f"v{target}"] = True
        return result

    return migrate


def test_current_plan_migration_is_deterministic_noop() -> None:
    original = _current_data()
    result = migrate_plan_data(original)
    assert result.source_version == 2
    assert result.target_version == 2
    assert result.steps == ()
    assert not result.changed
    assert result.data == original
    assert original == _current_data()


def test_migration_does_not_mutate_input() -> None:
    original = _current_data()
    before = deepcopy(original)
    migrate_plan_data(original)
    assert original == before


def test_migrate_json_roundtrips_current_plan() -> None:
    result = migrate_plan_json(json.dumps(_current_data()))
    assert '"schema_version": 2' in result
    assert '"format": "utterplan"' in result


def test_synthetic_chain_supports_one_and_multiple_steps() -> None:
    base = {"format": "utterplan", "schema_version": 1}
    result, steps = _apply_migration_chain(
        base,
        target_version=2,
        registry={1: _step(2)},
    )
    assert result["schema_version"] == 2
    assert steps == (MigrationStep(1, 2),)

    result, steps = _apply_migration_chain(
        base,
        target_version=3,
        registry={1: _step(2), 2: _step(3)},
    )
    assert result["schema_version"] == 3
    assert steps == (MigrationStep(1, 2), MigrationStep(2, 3))


def test_synthetic_chain_supports_starting_at_intermediate_version() -> None:
    result, steps = _apply_migration_chain(
        {"format": "utterplan", "schema_version": 2},
        target_version=3,
        registry={2: _step(3)},
    )
    assert result["schema_version"] == 3
    assert steps == (MigrationStep(2, 3),)


def test_missing_migration_path_is_explicit() -> None:
    with pytest.raises(MigrationPathError, match="migration.no-path"):
        _apply_migration_chain(
            {"format": "utterplan", "schema_version": 1},
            target_version=2,
            registry={},
        )


def test_invalid_step_output_is_rejected() -> None:
    with pytest.raises(PlanMigrationError, match="migration.step-invalid"):
        _apply_migration_chain(
            {"format": "utterplan", "schema_version": 1},
            target_version=2,
            registry={1: _step(3)},
        )


def test_mutating_step_is_rejected() -> None:
    def mutate(data):
        data["changed"] = True
        return data

    with pytest.raises(PlanMigrationError, match="mutated its input"):
        _apply_migration_chain(
            {"format": "utterplan", "schema_version": 1},
            target_version=2,
            registry={1: mutate},
        )


def test_future_schema_is_not_migrated() -> None:
    data = _current_data()
    data["schema_version"] = 3
    with pytest.raises(UnsupportedSchemaError):
        migrate_plan_data(data)


def test_downgrade_is_rejected() -> None:
    with pytest.raises(PlanMigrationError, match="migration.downgrade"):
        migrate_plan_data(_current_data(), target_version=0)
