---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: v0.6.12
kind: changed
summary: Preserved exact character spelling and adopted RenderPlan v2 binding catalogs
status: accepted
audience: null
scopes: []
source_refs:
  - tl:task-0050
paths:
  - utterplan/flow_projection.py
  - pyproject.toml
  - tests/test_renderplan_export.py
  - docs/format.md
issues: []
prs: []
sources: []
contributors: []
breaking: false
internal: false
order: 1
---

Character-spelling tokens retain exact surface case in portable lemmas despite context-sensitive provider output. Generated RenderPlans store each used role binding once at plan scope; loading still exposes the complete SpeechItem.binding mapping.
