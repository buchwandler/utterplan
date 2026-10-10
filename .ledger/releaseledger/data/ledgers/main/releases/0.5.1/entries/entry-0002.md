---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0002
release_version: 0.5.1
kind: changed
summary:
  Improved sentence topology with validated fallback recovery and token-edge
  safeguards
status: accepted
audience: null
scopes: []
source_refs:
  - git:1ae820690dfdfb7f9c5da46ff426a3513fb1ea94
paths:
  - docs/architecture.md
  - docs/coordinate-spaces.md
  - docs/debugging.md
  - docs/format.md
  - docs/python-api.md
  - tests/migration/goldens/multilingual_preparation.json
  - tests/migration/goldens/ssmd_break.json
  - tests/test_cli.py
  - tests/test_cli_batch.py
  - tests/test_consumer_contract.py
  - tests/test_flow_compilation.py
  - tests/test_linguistics.py
  - tests/test_planner.py
  - tests/test_renderability_repair.py
  - tests/test_segment_topology.py
  - tests/test_segmentation_adapter.py
  - tests/test_segmentation_recovery.py
  - tests/test_sentence_topology.py
  - tests/test_ssmd_09_parser.py
  - tests/test_token_topology.py
  - utterplan/flow_projection.py
  - utterplan/planner.py
  - utterplan/segmentation.py
  - utterplan/token_topology.py
issues: []
prs: []
sources:
  - git:1ae820690dfdfb7f9c5da46ff426a3513fb1ea94
contributors:
  - "@holgern"
breaking: false
internal: false
order: 2
---
