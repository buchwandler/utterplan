---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 2
entry_id: entry-0002
release_version: 0.3.4
kind: fixed
summary: Fixed renderer segmentation to retain adjacent neutral punctuation
status: accepted
audience: null
scopes: []
source_refs:
  - tl:task-0022
paths:
  - utterplan/planner.py
  - utterplan/directives.py
  - docs/consumer-guide.md
issues: []
prs: []
sources: []
contributors: []
breaking: false
internal: false
order: 2
---

Semantic annotation boundaries no longer leave punctuation-only speech requests, and directive applicability preserves exact annotation spans.
