---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: v0.6.15
kind: fixed
summary:
  Fixed SSMD conversion to preserve authored spacing around substitutions and
  structural controls
status: accepted
audience: null
scopes: []
source_refs:
  - git:68f26be7623d8c7c86c9b6611f02f3768e5619ff
paths:
  - tests/migration/test_semantic_migration_regressions.py
  - tests/test_consumer_readiness.py
  - tests/test_coordinates.py
  - tests/test_explain.py
  - tests/test_flow_compilation.py
  - tests/test_golden.py
  - tests/test_preparation.py
  - tests/test_renderplan_export.py
  - tests/test_ssmd_09_parser.py
  - tests/test_ssmd_substitution_preparation.py
  - utterplan/parsers.py
issues: []
prs: []
sources:
  - git:68f26be7623d8c7c86c9b6611f02f3768e5619ff
contributors:
  - "@holgern"
breaking: false
internal: false
order: 1
---
