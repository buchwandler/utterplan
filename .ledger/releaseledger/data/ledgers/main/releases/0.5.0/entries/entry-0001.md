---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 2
entry_id: entry-0001
release_version: 0.5.0
kind: changed
summary:
  Changed plan persistence to schema v5 with deterministic TOML, sequential
  legacy migration, and optional trace sidecars
status: accepted
audience: null
scopes: []
source_refs:
  - git:037fe92f62a34f3357700eb852a1fb89a3cbe4e5
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
  - docs/pykokoro-integration.md
  - docs/python-api.md
  - examples/compile_file.py
  - examples/inspect_plan.py
  - examples/multilingual.py
  - tests/compiler_helpers.py
  - tests/fixtures/canonical_consumer_contract.expected.toml
  - tests/migration/test_legacy_json_import.py
  - tests/migration/test_semantic_migration_regressions.py
  - tests/test_batch.py
  - tests/test_boundaries.py
  - tests/test_cli.py
  - tests/test_cli_batch.py
  - tests/test_compiler.py
  - tests/test_consumer_contract.py
  - tests/test_consumer_readiness.py
  - tests/test_coordinates.py
  - tests/test_directives.py
  - tests/test_explain.py
  - tests/test_fake_renderer.py
  - tests/test_flow_compilation.py
  - tests/test_format.py
  - tests/test_golden.py
  - tests/test_identity_units.py
  - tests/test_linguistics.py
  - tests/test_migration_framework.py
  - tests/test_migration_v3_to_v4.py
  - tests/test_migration_v4_to_v5.py
  - tests/test_pauses.py
  - tests/test_planner.py
  - tests/test_preparation.py
  - tests/test_progress.py
  - tests/test_public_identity.py
  - tests/test_renderability.py
  - tests/test_renderability_repair.py
  - tests/test_schema_history.py
  - tests/test_schema_registry.py
  - tests/test_schema_strict.py
  - tests/test_segment_topology.py
  - tests/test_semantic_boundaries.py
  - tests/test_ssmd_09_parser.py
  - tests/test_toml_format.py
  - utterplan/__init__.py
  - utterplan/attempt_serialization.py
  - utterplan/batch.py
  - utterplan/cli.py
  - utterplan/codecs/__init__.py
  - utterplan/codecs/v4_toml.py
  - utterplan/codecs/v5_toml.py
  - utterplan/compiler.py
  - utterplan/config.py
  - utterplan/explain.py
  - utterplan/flow_projection.py
  - utterplan/format.py
  - utterplan/hashing.py
  - utterplan/migration.py
  - utterplan/migrations/__init__.py
  - utterplan/migrations/v4_to_v5.py
  - utterplan/model.py
  - utterplan/parsers.py
  - utterplan/pauses.py
  - utterplan/planner.py
  - utterplan/preparation.py
  - utterplan/renderability.py
  - utterplan/schema_registry.py
  - utterplan/serialization.py
  - utterplan/toml_codec.py
  - utterplan/trace_codec.py
  - utterplan/versioning.py
issues: []
prs: []
sources:
  - git:037fe92f62a34f3357700eb852a1fb89a3cbe4e5
contributors:
  - "@holgern"
breaking: true
internal: false
order: 1
---
