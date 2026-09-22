---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: 0.2.0
kind: added
summary:
  Added schema version 2 with embedded token annotations, linguistic run provenance,
  and a v1-to-v2 migration
status: accepted
audience: null
scopes: []
source_refs:
  - git:c52aa684cc872d348d90972001a8c5194ae7c7f8
paths:
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
  - pyproject.toml
  - spec/schemas/v2.schema.json
  - spec/utterplan.schema.json
  - tests/golden/basic_en.utterplan.json
  - tests/golden/directives.utterplan.json
  - tests/golden/markers.utterplan.json
  - tests/golden/multilingual.utterplan.json
  - tests/golden/parenthetical.utterplan.json
  - tests/golden/spokenform_offsets.utterplan.json
  - tests/golden/ssmd_breaks.utterplan.json
  - tests/test_cli.py
  - tests/test_explain.py
  - tests/test_format.py
  - tests/test_linguistics.py
  - tests/test_migration_framework.py
  - tests/test_public_identity.py
  - tests/test_schema_history.py
  - tests/test_schema_registry.py
  - utterplan/__init__.py
  - utterplan/cli.py
  - utterplan/explain.py
  - utterplan/hashing.py
  - utterplan/linguistics.py
  - utterplan/migrations/__init__.py
  - utterplan/migrations/registry.py
  - utterplan/migrations/v1_to_v2.py
  - utterplan/model.py
  - utterplan/planner.py
  - utterplan/schema_registry.py
  - utterplan/schemas/v2.schema.json
  - utterplan/units.py
  - utterplan/utterplan.schema.json
  - utterplan/versioning.py
issues: []
prs: []
sources:
  - git:c52aa684cc872d348d90972001a8c5194ae7c7f8
contributors:
  - "@holgern"
breaking: false
internal: false
order: 1
---

Serialized plans can now be written as schema version 2, which embeds token annotations with lemma, pos, tag, and morph fields and records linguistic run provenance (provider, model, provider version, model version). Unit content hashes move to the utterplan-unit-v2 payload that includes tokens. Older v1 files upgrade through the registered v1-to-v2 migration while v1 stays frozen, and spaCy support is available through the spacy optional extra.
