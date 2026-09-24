---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0002
release_version: 0.3.0
kind: fixed
summary: Fixed precedence so authored SSMD breaks override generated pauses
status: accepted
audience: null
scopes: []
source_refs: []
paths:
  - utterplan/pauses.py
  - tests/test_pauses.py
  - tests/test_ssmd_09_parser.py
issues: []
prs: []
sources:
  - tl:task-0017
contributors: []
breaking: false
internal: false
order: 2
---

At a shared boundary, an explicit SSMD break wins over automatic or default pauses. Durations are not added, all contributing event IDs remain in provenance, and an authored zero-duration break still takes precedence.
