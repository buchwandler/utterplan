---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: 0.3.1
kind: added
summary:
  Added renderer-neutral SSMD audio segments with opaque sources and optional
  spoken fallback
status: accepted
audience: null
scopes: []
source_refs:
  - git:70adac05bf008abfed0e8ea46eb9d0973ba1cd82
paths:
  - docs/consumer-guide.md
  - docs/python-api.md
  - tests/test_consumer_contract.py
  - tests/test_directives.py
  - tests/test_fake_renderer.py
  - tests/test_format.py
  - tests/test_identity_units.py
  - tests/test_planner.py
  - tests/test_preparation.py
  - tests/test_ssmd_09_parser.py
  - utterplan/parsers.py
  - utterplan/planner.py
issues: []
prs: []
sources:
  - git:70adac05bf008abfed0e8ea46eb9d0973ba1cd82
contributors:
  - "@holgern"
breaking: false
internal: false
order: 1
---

Each SSMD audio annotation maps to one segment carrying `directives.audio`; the source remains opaque and `segment.text` is optional fallback (empty when absent). Repeated sources remain distinct occurrences.
