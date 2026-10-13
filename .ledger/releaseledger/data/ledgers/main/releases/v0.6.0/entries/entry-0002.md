---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0002
release_version: v0.6.0
kind: changed
summary:
  Changed written-to-spoken preparation to route through TTSReady with a stable
  spokenform compatibility label
status: accepted
audience: null
scopes: []
source_refs:
  - git:4abca5cfad32ac0f9c4987dbeadcbafa232c785b
paths:
  - README.md
  - docs/architecture.md
  - docs/consumer-guide.md
  - docs/getting-started.md
  - docs/python-api.md
  - pyproject.toml
  - tests/migration/cases.py
  - tests/test_cli.py
  - tests/test_consumer_contract.py
  - tests/test_dependency_architecture.py
  - tests/test_import_boundaries.py
  - tests/test_linguistics.py
  - tests/test_migration_v4_to_v5.py
  - tests/test_planner.py
  - tests/test_preparation.py
  - tests/test_replacement_provenance.py
  - tests/test_ttsready_preparation_adapter.py
  - utterplan/codecs/v5_toml.py
  - utterplan/flow_projection.py
  - utterplan/model.py
  - utterplan/planner.py
  - utterplan/preparation.py
  - utterplan/stages/preparation/spokenform.py
  - utterplan/stages/preparation/ttsready.py
issues: []
prs: []
sources:
  - git:4abca5cfad32ac0f9c4987dbeadcbafa232c785b
contributors:
  - "@holgern"
breaking: false
internal: false
order: 2
---
