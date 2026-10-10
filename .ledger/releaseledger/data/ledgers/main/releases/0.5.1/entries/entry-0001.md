---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: 0.5.1
kind: fixed
summary:
  Fixed fallback token projection and sentence-boundary repair for punctuation-separated
  text
status: accepted
audience: null
scopes: []
source_refs:
  - git:f143f17dff20963d4285a8142014ecfbde2821ee
paths:
  - tests/test_cli_ssmdbook.py
  - tests/test_flow_compilation.py
  - tests/test_planner.py
  - utterplan/flow_projection.py
  - utterplan/planner.py
issues: []
prs: []
sources:
  - git:f143f17dff20963d4285a8142014ecfbde2821ee
contributors:
  - "@holgern"
breaking: false
internal: false
order: 1
---
