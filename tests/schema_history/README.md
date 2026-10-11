# Schema history fixtures

Files under `tests/schema_history/<version>/` are immutable historical UtterPlan
fixtures. They represent released serialized plans and must not be regenerated
from the current planner.

Schemas v1, v2, and v3 are immutable historical resources; the v3 fixtures capture the released schema-v3 plan shape. The v5 TOML fixture is a frozen consumer contract; schema v5 has no JSON Schema resource. Every supported historical fixture must continue to validate against its frozen contract and load through the public migration-aware API, with sequential migration paths retained. Schema v6 likewise uses its versioned TOML/model contract rather than a historical JSON Schema resource.
