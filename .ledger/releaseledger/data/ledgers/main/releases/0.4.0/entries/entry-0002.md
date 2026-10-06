---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0002
release_version: 0.4.0
kind: changed
summary:
  Changed serialized plans to schema v4 with deterministic v3-to-v4 migration
  and boundary-sensitive unit identity
status: accepted
audience: null
scopes: []
source_refs: []
paths:
  - utterplan/migrations/v3_to_v4.py
  - utterplan/hashing.py
  - utterplan/units.py
  - utterplan/versioning.py
issues: []
prs: []
sources:
  - tl:task-0024
contributors: []
breaking: false
internal: false
order: 2
---

Schema v1 through v3 resources remain frozen. Migration operates on serialized plain data, preserves provenance, derives only deterministic topology, and does not reparse or replan. Current unit identity uses utterplan-unit-v3 with relative semantic-boundary positions.
