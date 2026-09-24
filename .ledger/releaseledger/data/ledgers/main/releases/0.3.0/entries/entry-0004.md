---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0004
release_version: 0.3.0
kind: changed
summary: Changed clause enrichment to reuse provider-owned spaCy docs
status: accepted
audience: null
scopes: []
source_refs: []
paths:
  - utterplan/planner.py
  - tests/test_linguistics.py
issues: []
prs: []
sources:
  - tl:task-0017
contributors: []
breaking: false
internal: false
order: 4
---

Clausal-boundary enrichment reuses the request-local provider document when available. Fallback analysis does not infer syntactic clauses, and sentence topology remains on the deterministic spaCy-free segmentation path.
