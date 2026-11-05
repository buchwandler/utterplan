---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: 0.6.18
kind: added
summary:
  Added read-only bundle freshness inspection with incremental selectors and
  profile/config drift diagnostics
status: accepted
audience: null
scopes: []
source_refs:
  - git:2f84aa1e376b7f887a19ca8782adedce5637aabc
paths:
  - tests/test_bundle_book_services.py
  - tests/test_bundle_services.py
  - utterplan/__init__.py
  - utterplan/batch.py
  - utterplan/bundle_inspection.py
  - utterplan/config.py
issues: []
prs: []
sources:
  - git:2f84aa1e376b7f887a19ca8782adedce5637aabc
contributors:
  - "@holgern"
breaking: false
internal: false
order: 1
---
