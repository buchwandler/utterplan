# Schema history fixtures

Files under `tests/schema_history/<version>/` are immutable historical UtterPlan
fixtures. They represent released serialized plans and must not be regenerated
from the current planner.

Schemas v1 and v2 remain immutable. Schema v3 is current. Every supported
historical fixture must continue to validate against its frozen schema and load
through the public migration-aware API, with sequential migration paths retained.
