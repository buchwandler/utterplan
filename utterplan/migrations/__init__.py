from __future__ import annotations

from .registry import migration_registry, register_migration
from .v1_to_v2 import migrate_v1_to_v2
from .v2_to_v3 import migrate_v2_to_v3
from .v3_to_v4 import migrate_v3_to_v4
from .v4_to_v5 import migrate_v4_to_v5

__all__ = [
    "migration_registry",
    "register_migration",
    "migrate_v1_to_v2",
    "migrate_v2_to_v3",
    "migrate_v3_to_v4",
    "migrate_v4_to_v5",
]
