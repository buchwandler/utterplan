---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0004
release_version: 0.4.0
kind: changed
summary:
  Changed plan persistence to deterministic TOML with explicit legacy JSON
  import and incremental batch compilation
status: accepted
audience: null
scopes: []
source_refs:
  - git:fb6e0c70bef1d84d1aef1edd625e230eef2c7aec
paths:
  - utterplan/toml_codec.py
  - utterplan/cli.py
  - utterplan/batch.py
  - utterplan/atomic_io.py
  - utterplan/migration.py
  - docs/format.md
issues: []
prs: []
sources: []
contributors: []
breaking: false
internal: false
order: 4
---

Canonical plans now save and load as TOML, legacy JSON is imported explicitly without replanning, and compile-many writes successful plans atomically while preserving per-item outcomes in a TOML report.
