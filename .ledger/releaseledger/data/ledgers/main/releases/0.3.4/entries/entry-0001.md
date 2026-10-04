---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: 0.3.4
kind: added
summary: Added typed planner progress events and reused unchanged linguistic analyses
status: accepted
audience: null
scopes: []
source_refs:
  - tl:task-0021
paths:
  - utterplan/progress.py
  - utterplan/planner.py
  - utterplan/linguistics.py
  - utterplan/compiler.py
  - tests/test_progress.py
  - tests/test_linguistics.py
  - docs/python-api.md
  - README.md
issues: []
prs: []
sources: []
contributors: []
breaking: false
internal: false
order: 1
---

The optional synchronous callback reports planner phases, provider runs, and actual spaCy model loads without changing plan serialization; equivalent analyses are reused where safe.
