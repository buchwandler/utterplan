---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0005
release_version: 0.3.0
kind: added
summary: Added PEP 561 metadata and SSMD 0.9 package checks
status: accepted
audience: null
scopes: []
source_refs: []
paths:
  - utterplan/py.typed
  - pyproject.toml
  - .github/workflows/tests.yml
  - .github/workflows/python-publish.yml
issues: []
prs: []
sources:
  - tl:task-0017
contributors: []
breaking: false
internal: false
order: 5
---

Wheel and source-distribution checks require the PEP 561 marker, all schema resources, and the SSMD 0.9 dependency range. Installed-package smoke coverage accepts strict 0.9 input and rejects an explicit 0.8 header.
