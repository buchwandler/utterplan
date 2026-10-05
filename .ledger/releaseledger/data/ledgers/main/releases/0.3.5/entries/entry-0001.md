---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: 0.3.5
kind: fixed
summary:
  Fixed planner segmentation to keep neutral punctuation with adjacent speech
  while preserving exact annotation spans
status: accepted
audience: null
scopes: []
source_refs:
  - git:a19ceb434bd7277c6c78a91ad8e96ca840367600
paths:
  - .ledger/releaseledger/data/ledgers/main/events/events.jsonl
  - .ledger/releaseledger/data/ledgers/main/releases/0.3.4/entries/entry-0002.md
  - .ledger/releaseledger/data/ledgers/main/releases/0.3.4/release.md
  - docs/changelog.md
  - docs/consumer-guide.md
  - tests/golden/ssmd_09_comprehensive.utterplan.json
  - tests/migration/goldens/multilingual_preparation.json
  - tests/migration/goldens/ssmd_pronunciation.json
  - tests/test_segment_topology.py
  - utterplan/directives.py
  - utterplan/planner.py
issues: []
prs: []
sources:
  - git:a19ceb434bd7277c6c78a91ad8e96ca840367600
contributors:
  - "@holgern"
breaking: false
internal: false
order: 1
---
