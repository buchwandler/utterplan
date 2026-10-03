---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: 0.3.2
kind: fixed
summary:
  Fixed text preparation so authored SSMD substitutions and say-as annotations
  remain unchanged
status: accepted
audience: null
scopes: []
source_refs:
  - git:6c2a1ac444c76ea183a791b59af2e92fb60dbb23
paths:
  - tests/test_preparation.py
  - utterplan/preparation.py
issues: []
prs: []
sources:
  - git:6c2a1ac444c76ea183a791b59af2e92fb60dbb23
contributors:
  - "@holgern"
breaking: false
internal: false
order: 1
---

Spoken-text preparation excludes spans with `sub`, `as`, and `say-as` attributes from automatic spoken-form replacement, preserving author-provided text while retaining existing pronunciation protections.
