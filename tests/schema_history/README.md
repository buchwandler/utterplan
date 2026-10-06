# Schema history fixtures

Files under `tests/schema_history/<version>/` are immutable historical UtterPlan
fixtures. They represent released serialized plans and must not be regenerated
from the current planner.

Schemas v1, v2, and v3 are immutable historical resources; the v3 fixtures capture the released schema-v3 plan shape. Every supported
historical fixture must continue to validate against its frozen schema and load
through the public migration-aware API, with sequential migration paths retained.
