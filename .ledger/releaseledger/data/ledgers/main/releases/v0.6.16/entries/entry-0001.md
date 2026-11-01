---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: v0.6.16
kind: fixed
summary:
  Fixed RenderPlan token projection to omit blank optional metadata while preserving
  valid sparse values
status: accepted
audience: null
scopes: []
source_refs:
  - git:ab9257c3f8d6ac6572e9e261b3aab574260238b1
paths:
  - tests/test_linguistics.py
  - tests/test_renderplan_batch.py
  - tests/test_renderplan_v7_contract.py
  - tests/test_toml_format.py
  - utterplan/flow_projection.py
  - utterplan/renderplan_projection.py
issues: []
prs: []
sources:
  - git:ab9257c3f8d6ac6572e9e261b3aab574260238b1
contributors:
  - "@holgern"
breaking: false
internal: false
order: 1
---
