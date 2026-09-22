from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

MigrationFn = Callable[[Mapping[str, Any]], Mapping[str, Any]]

_MIGRATIONS: dict[int, MigrationFn] = {}


def register_migration(source_version: int, migration: MigrationFn) -> None:
    _MIGRATIONS[source_version] = migration


def migration_registry() -> dict[int, MigrationFn]:
    """Return a copy of the registered single-step migrations."""
    return dict(_MIGRATIONS)


__all__ = ["MigrationFn", "migration_registry", "register_migration"]
