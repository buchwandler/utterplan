---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: 0.3.6
kind: added
summary:
  Added strict renderability checks and deterministic repair for isolated neutral
  punctuation segments
status: accepted
audience: null
scopes: []
source_refs:
  - git:7576dd2dba4d312679ce0a844dd33686ebb7efe8
paths:
  - pyproject.toml
  - tests/golden/multilingual.utterplan.json
  - tests/golden/ssmd_09_comprehensive.utterplan.json
  - tests/migration/cases.py
  - tests/migration/goldens/multilingual_preparation.json
  - tests/migration/goldens/spokenform_numbers.json
  - tests/migration/goldens/ssmd_break.json
  - tests/migration/goldens/ssmd_language_detection.json
  - tests/migration/goldens/ssmd_marker.json
  - tests/migration/goldens/ssmd_pronunciation.json
  - tests/test_boundaries.py
  - tests/test_cli.py
  - tests/test_consumer_contract.py
  - tests/test_explain.py
  - tests/test_format.py
  - tests/test_planner.py
  - tests/test_preparation.py
  - tests/test_progress.py
  - tests/test_renderability.py
  - tests/test_renderability_repair.py
  - tests/test_schema_history.py
  - tests/test_segment_topology.py
  - tests/test_ssmd_09_parser.py
  - utterplan/__init__.py
  - utterplan/cli.py
  - utterplan/config.py
  - utterplan/exceptions.py
  - utterplan/model.py
  - utterplan/parsers.py
  - utterplan/planner.py
  - utterplan/renderability.py
issues: []
prs: []
sources:
  - git:7576dd2dba4d312679ce0a844dd33686ebb7efe8
contributors:
  - "@holgern"
breaking: false
internal: false
order: 1
---
