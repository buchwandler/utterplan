---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 2
entry_id: entry-0001
release_version: 0.4.0
kind: added
summary:
  Added stable spoken-coordinate semantic boundaries for clause, parenthetical,
  sentence, and paragraph splits
status: accepted
audience: null
scopes: []
source_refs:
  - tl:task-0024
paths:
  - utterplan/model.py
  - utterplan/planner.py
  - utterplan/schemas/v4.schema.json
issues: []
prs: []
sources: []
contributors: []
breaking: false
internal: false
order: 1
---

Semantic boundaries are immutable engine-neutral consumer input and remain separate from pause/timing events. Public range and segment lookup helpers expose these opportunities without provider documents or renderer dependencies.
