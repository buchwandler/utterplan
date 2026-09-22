---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0004
release_version: 0.2.0
kind: internal
summary: Improved formatting in schema files, golden fixtures, and Python modules
status: accepted
audience: null
scopes: []
source_refs:
  - git:9637182acbf51763706e1047283b6df27def4bb8
paths:
  - docs/cli.md
  - docs/consumer-guide.md
  - docs/getting-started.md
  - docs/pykokoro-integration.md
  - docs/python-api.md
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
  - tests/test_format.py
  - tests/test_linguistics.py
  - tests/test_schema_history.py
  - utterplan/explain.py
  - utterplan/hashing.py
  - utterplan/migrations/v1_to_v2.py
  - utterplan/model.py
  - utterplan/planner.py
  - utterplan/schemas/v2.schema.json
  - utterplan/utterplan.schema.json
issues: []
prs: []
sources:
  - git:9637182acbf51763706e1047283b6df27def4bb8
contributors:
  - "@holgern"
breaking: false
internal: true
order: 4
---

Formatter-only normalization. Golden fixtures were compacted to single-line JSON arrays, schema required arrays expanded and rewrapped, and Python sources rewrapped. No serialization, validation, migration, or planning behavior changed.
