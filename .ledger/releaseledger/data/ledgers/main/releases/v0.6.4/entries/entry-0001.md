---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: v0.6.4
kind: added
summary:
  Added compile-document for editable SSMDDoc workspaces with safe source loading
  and plan reports
status: accepted
audience: null
scopes: []
source_refs:
  - git:60e6be0d43e092f854e246a681b844453034693e
paths:
  - .ledger/archledger/data/document-state.json
  - .ledger/archledger/data/profiles/arc42/sections/content-0001.md
  - .ledger/archledger/data/profiles/arc42/sections/content-0003.md
  - .ledger/archledger/data/profiles/arc42/sections/content-0005.md
  - .ledger/archledger/data/profiles/arc42/sections/content-0006.md
  - .ledger/archledger/data/profiles/arc42/sections/content-0007.md
  - .ledger/archledger/data/profiles/arc42/sections/content-0009.md
  - .ledger/archledger/data/profiles/arc42/sections/content-0012.md
  - MANIFEST.in
  - README.md
  - docs/architecture.md
  - docs/cli.md
  - docs/index.md
  - docs/ssmdoc.md
  - tests/fixtures/ssmdoc-v1/story.ssmdoc/document.ssmd.md
  - tests/fixtures/ssmdoc-v1/story.ssmdoc/manifest.json
  - tests/test_cli.py
  - tests/test_cli_ssmdoc.py
  - tests/test_document_workspace.py
  - tests/test_source_input.py
  - tests/test_ssmdoc.py
  - utterplan/__init__.py
  - utterplan/cli.py
  - utterplan/document_workspace.py
  - utterplan/source_input.py
  - utterplan/ssmdoc.py
issues: []
prs: []
sources:
  - git:60e6be0d43e092f854e246a681b844453034693e
contributors:
  - "@holgern"
breaking: false
internal: false
order: 1
---
