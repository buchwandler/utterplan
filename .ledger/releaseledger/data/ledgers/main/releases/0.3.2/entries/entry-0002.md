---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0002
release_version: 0.3.2
kind: added
summary: Added SSMD sequence fallback mode controls for spoken-form preparation
status: accepted
audience: null
scopes: []
source_refs:
  - git:ba3b5afb6c619cf91e482db16b19d53f199eb1e2
paths:
  - tests/golden/ssmd_09_comprehensive.utterplan.json
  - tests/migration/goldens/multilingual_preparation.json
  - tests/migration/goldens/spokenform_numbers.json
  - tests/migration/goldens/ssmd_break.json
  - tests/migration/goldens/ssmd_language_detection.json
  - tests/migration/goldens/ssmd_marker.json
  - tests/migration/goldens/ssmd_pronunciation.json
  - tests/test_consumer_readiness.py
  - tests/test_preparation.py
  - tests/test_ssmd_09_parser.py
  - utterplan/parsers.py
  - utterplan/planner.py
  - utterplan/preparation.py
issues: []
prs: []
sources:
  - git:ba3b5afb6c619cf91e482db16b19d53f199eb1e2
contributors:
  - "@holgern"
breaking: false
internal: false
order: 2
---

SSMD headers can choose `spell` or `preserve` for sequence fallback behavior. The default remains `spell`; the selected mode is carried in plan metadata, and invalid values are rejected during planning.
