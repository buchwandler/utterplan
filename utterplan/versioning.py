from __future__ import annotations

FORMAT = "utterplan"
CURRENT_SCHEMA_VERSION = 7
OLDEST_SUPPORTED_SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)
JSON_SCHEMA_VERSIONS: tuple[int, ...] = (1, 2, 3, 4)
V4_SCHEMA_VERSION = 4
V5_SCHEMA_VERSION = 5
V6_SCHEMA_VERSION = 6
# Compatibility alias retained for callers that mean the current schema.
SCHEMA_VERSION = CURRENT_SCHEMA_VERSION
