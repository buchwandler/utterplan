---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0002
release_version: 0.2.0
kind: changed
summary:
  Improved inspect and explain output with token annotations and linguistic
  run metadata
status: accepted
audience: null
scopes: []
source_refs: []
paths:
  - utterplan/cli.py
  - utterplan/explain.py
issues: []
prs: []
sources:
  - git:c52aa684cc872d348d90972001a8c5194ae7c7f8
contributors:
  - "@holgern"
breaking: false
internal: false
order: 2
---

The inspect token view reports provider and model provenance alongside per-token lemma, pos, tag, and morph values. Detailed explain output lists each segment's tokens and the linguistic run information behind them.
