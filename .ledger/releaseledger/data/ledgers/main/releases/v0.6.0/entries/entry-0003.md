---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0003
release_version: v0.6.0
kind: added
summary:
  Added schema v6 source provenance, source-aware identity, SSMD preparation,
  and sequential migration
status: accepted
audience: null
scopes: []
source_refs:
  - git:1a807cc4f865ad55a1a31e531288fe931f8aec71
paths:
  - AGENTS.md
  - README.md
  - docs/architecture.md
  - docs/cli.md
  - docs/consumer-guide.md
  - docs/coordinate-spaces.md
  - docs/debugging.md
  - docs/format.md
  - docs/getting-started.md
  - docs/index.md
  - docs/pykokoro-integration.md
  - docs/python-api.md
  - docs/ssmdbook.md
  - tests/migration/cases.py
  - tests/migration/test_legacy_json_import.py
  - tests/migration/test_semantic_migration_regressions.py
  - tests/schema_history/README.md
  - tests/schema_history/v5/canonical_consumer_contract.toml
  - tests/test_batch.py
  - tests/test_cli.py
  - tests/test_cli_ssmdbook.py
  - tests/test_consumer_contract.py
  - tests/test_consumer_readiness.py
  - tests/test_coordinates.py
  - tests/test_explain.py
  - tests/test_flow_compilation.py
  - tests/test_format.py
  - tests/test_golden.py
  - tests/test_linguistics.py
  - tests/test_migration_framework.py
  - tests/test_migration_v4_to_v5.py
  - tests/test_planner.py
  - tests/test_preparation.py
  - tests/test_public_identity.py
  - tests/test_replacement_provenance.py
  - tests/test_schema_history.py
  - tests/test_schema_registry.py
  - tests/test_schema_v6_source.py
  - tests/test_segmentation_recovery.py
  - tests/test_ssmd_09_parser.py
  - tests/test_ssmd_substitution_preparation.py
  - tests/test_toml_format.py
  - tests/test_ttsready_preparation_adapter.py
  - utterplan/__init__.py
  - utterplan/batch.py
  - utterplan/cli.py
  - utterplan/codecs/v5_toml.py
  - utterplan/codecs/v6_toml.py
  - utterplan/compiler.py
  - utterplan/config.py
  - utterplan/directives.py
  - utterplan/explain.py
  - utterplan/flow_projection.py
  - utterplan/format.py
  - utterplan/hashing.py
  - utterplan/migration.py
  - utterplan/migrations/__init__.py
  - utterplan/migrations/v4_to_v5.py
  - utterplan/migrations/v5_to_v6.py
  - utterplan/model.py
  - utterplan/planner.py
  - utterplan/preparation.py
  - utterplan/schema_registry.py
  - utterplan/segmentation.py
  - utterplan/serialization.py
  - utterplan/stages/preparation/ssmd.py
  - utterplan/toml_codec.py
  - utterplan/versioning.py
issues: []
prs: []
sources:
  - git:1a807cc4f865ad55a1a31e531288fe931f8aec71
contributors:
  - "@holgern"
breaking: false
internal: false
order: 3
---
