---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: v0.6.6
kind: added
summary:
  Added manifest-driven bundle services for compiling, rendering, and replanning
  book or document .ssmd-bundle roots
status: accepted
audience: null
scopes: []
source_refs:
  - git:5ef16474f003b2a28815b0b9258b28e6d8c14490
paths:
  - utterplan/ssmd_bundle.py
  - utterplan/bundle.py
  - utterplan/bundle_replan.py
  - utterplan/cli.py
  - utterplan/__init__.py
  - docs/bundles.md
  - tests/test_ssmd_bundle.py
  - tests/test_ssmd_bundle_book.py
  - tests/test_ssmd_bundle_document.py
  - tests/test_bundle_services.py
  - tests/test_bundle_replan.py
issues: []
prs: []
sources:
  - git:5ef16474f003b2a28815b0b9258b28e6d8c14490
contributors:
  - "@holgern"
breaking: false
internal: false
order: 1
---
