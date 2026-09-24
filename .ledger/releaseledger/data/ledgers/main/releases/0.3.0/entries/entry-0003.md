---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0003
release_version: 0.3.0
kind: changed
summary: Changed Python input defaults and renamed SSMDConfig options
status: accepted
audience: null
scopes: []
source_refs: []
paths:
  - utterplan/config.py
  - utterplan/parsers.py
  - utterplan/planner.py
  - docs/python-api.md
  - docs/consumer-guide.md
  - tests/test_consumer_readiness.py
issues: []
prs: []
sources:
  - tl:task-0017
contributors: []
breaking: true
internal: false
order: 3
---

PlannerConfig now treats strings as plain text unless SSMD is selected explicitly. The no-op strict_header and unknown_header options were removed; parse_header and the application pause_defaults option are now parse_yaml_header and pause_overrides. The source-header pause_defaults key remains unchanged.
