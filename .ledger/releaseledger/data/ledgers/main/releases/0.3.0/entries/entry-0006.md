---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0006
release_version: 0.3.0
kind: docs
summary: Documented the 0.2-to-0.3 migration paths
status: accepted
audience: null
scopes: []
source_refs: []
paths:
  - docs/consumer-guide.md
  - docs/python-api.md
  - docs/format.md
issues: []
prs: []
sources:
  - tl:task-0017
contributors: []
breaking: false
internal: false
order: 6
---

The migration guide separates SSMD source conversion with ssmd migrate from UtterPlan JSON schema migration. It documents the plain Python input default, SSMDConfig renames, and continued v1/v2 plan migration to schema v3.
