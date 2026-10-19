---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0002
release_version: v0.6.5
kind: changed
summary:
  Changed editable SSMDDoc workspaces to use stable utterplan and renderplan
  output directories
status: accepted
audience: null
scopes: []
source_refs:
  - git:a0edfc00862bcbc77a3746c963d6e9d23436c002
paths:
  - .ledger/archledger/data/document-state.json
  - .ledger/archledger/data/profiles/arc42/sections/content-0001.md
  - .ledger/archledger/data/profiles/arc42/sections/content-0003.md
  - .ledger/archledger/data/profiles/arc42/sections/content-0006.md
  - .ledger/archledger/data/profiles/arc42/sections/content-0007.md
  - README.md
  - docs/architecture.md
  - docs/cli.md
  - docs/ssmdoc.md
  - tests/test_cli_render_document.py
  - tests/test_cli_ssmdoc.py
  - tests/test_document_render.py
  - tests/test_document_workspace.py
  - tests/test_import_boundaries.py
  - tests/test_ssmdoc.py
  - utterplan/book.py
  - utterplan/cli.py
  - utterplan/document_workspace.py
  - utterplan/source_input.py
  - utterplan/ssmdoc.py
  - utterplan/workspace_paths.py
issues: []
prs: []
sources:
  - git:a0edfc00862bcbc77a3746c963d6e9d23436c002
contributors:
  - "@holgern"
breaking: false
internal: false
order: 2
---
