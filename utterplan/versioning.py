from __future__ import annotations

FORMAT = "utterplan"
FORMAT = "utterplan"
CURRENT_SCHEMA_VERSION = 5
OLDEST_SUPPORTED_SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS: tuple[int, ...] = (1, 2, 3, 4, 5)
JSON_SCHEMA_VERSIONS: tuple[int, ...] = (1, 2, 3, 4)
V4_SCHEMA_VERSION = 4
# Compatibility alias retained for callers that mean the current schema.
SCHEMA_VERSION = CURRENT_SCHEMA_VERSION
