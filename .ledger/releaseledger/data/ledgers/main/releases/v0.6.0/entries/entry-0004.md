---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0004
release_version: v0.6.0
kind: added
summary:
  Added schema v7 paragraph-local flow units and safe boundary opportunities
  separate from authored pauses
status: accepted
audience: null
scopes: []
source_refs:
  - git:98080aa46e015fd7e4e24a40d6f9a77c2aa55666
paths:
  - README.md
  - docs/architecture.md
  - docs/cli.md
  - docs/consumer-guide.md
  - docs/coordinate-spaces.md
  - docs/debugging.md
  - docs/format.md
  - docs/getting-started.md
  - docs/pykokoro-integration.md
  - docs/python-api.md
  - docs/ssmdbook.md
  - tests/compiler_helpers.py
  - tests/migration/cases.py
  - tests/migration/test_legacy_json_import.py
  - tests/migration/test_semantic_migration_regressions.py
  - tests/test_boundaries.py
  - tests/test_cli.py
  - tests/test_cli_ssmdbook.py
  - tests/test_compiler.py
  - tests/test_consumer_contract.py
  - tests/test_consumer_readiness.py
  - tests/test_explain.py
  - tests/test_fake_renderer.py
  - tests/test_flow_compilation.py
  - tests/test_format.py
  - tests/test_golden.py
  - tests/test_identity_units.py
  - tests/test_linguistics.py
  - tests/test_migration_framework.py
  - tests/test_pauses.py
  - tests/test_planner.py
  - tests/test_public_identity.py
  - tests/test_renderability.py
  - tests/test_renderability_repair.py
  - tests/test_replacement_provenance.py
  - tests/test_schema_history.py
  - tests/test_schema_registry.py
  - tests/test_schema_v6_source.py
  - tests/test_schema_v7.py
  - tests/test_semantic_boundaries.py
  - tests/test_ssmd_09_parser.py
  - tests/test_toml_format.py
  - utterplan/__init__.py
  - utterplan/boundaries.py
  - utterplan/cli.py
  - utterplan/codecs/v5_toml.py
  - utterplan/codecs/v6_toml.py
  - utterplan/codecs/v7_toml.py
  - utterplan/config.py
  - utterplan/explain.py
  - utterplan/flow_projection.py
  - utterplan/format.py
  - utterplan/hashing.py
  - utterplan/migrations/__init__.py
  - utterplan/migrations/v5_to_v6.py
  - utterplan/migrations/v6_to_v7.py
  - utterplan/model.py
  - utterplan/pauses.py
  - utterplan/planner.py
  - utterplan/renderability.py
  - utterplan/schema_registry.py
  - utterplan/serialization.py
  - utterplan/toml_codec.py
  - utterplan/units.py
  - utterplan/versioning.py
issues: []
prs: []
sources:
  - git:98080aa46e015fd7e4e24a40d6f9a77c2aa55666
contributors:
  - "@holgern"
breaking: false
internal: false
order: 4
---
