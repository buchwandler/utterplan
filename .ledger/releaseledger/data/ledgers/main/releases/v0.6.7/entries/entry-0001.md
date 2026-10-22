---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: v0.6.7
kind: fixed
summary: Fixed bundle path detection when a path resolves to an SSMD bundle root
status: accepted
audience: null
scopes: []
source_refs: []
paths:
  - utterplan/ssmd_bundle.py
  - utterplan/cli.py
  - docs/bundles.md
issues: []
prs: []
sources: []
contributors: []
breaking: false
internal: false
order: 1
---

Current-directory and equivalent path aliases now work when they resolve to a canonical bundle root; invalid roots remain rejected.
