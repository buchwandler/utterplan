---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0002
release_version: v0.6.9
kind: changed
summary:
  Changed bundle rendering and replanning to use validated profile identities
  and keep --force limited to valid outputs
status: accepted
audience: null
scopes: []
source_refs:
  - git:3b80a28101da9e916b2790ede5c28fdef1047ada
paths:
  - README.md
  - docs/bundles.md
  - docs/cli.md
  - docs/debugging.md
  - tests/test_cli_bundle_render_book.py
  - tests/test_cli_bundle_render_document.py
  - tests/test_renderplan_export.py
  - utterplan/_book_service.py
  - utterplan/_document_service.py
  - utterplan/bundle_replan.py
  - utterplan/cli.py
issues: []
prs: []
sources:
  - git:3b80a28101da9e916b2790ede5c28fdef1047ada
contributors:
  - "@holgern"
breaking: false
internal: false
order: 2
---
