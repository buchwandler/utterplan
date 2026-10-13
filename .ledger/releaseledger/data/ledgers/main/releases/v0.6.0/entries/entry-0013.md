---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0013
release_version: v0.6.0
kind: changed
summary:
  Changed normal plan loading to accept schema v7 only and aligned the RenderPlan
  0.1.1 contract
status: accepted
audience: null
scopes: []
source_refs:
  - git:50dd54d4a3670cd9ca05cf3190c6f4b2f1330b9f
paths:
  - .github/workflows/tests.yml
  - docs/architecture.md
  - docs/cli.md
  - docs/consumer-guide.md
  - docs/format.md
  - docs/index.md
  - docs/python-api.md
  - pyproject.toml
  - tests/test_cli.py
  - tests/test_cli_render_book.py
  - tests/test_golden.py
  - tests/test_renderplan_batch.py
  - tests/test_renderplan_dependency_contract.py
  - tests/test_renderplan_export.py
  - tests/test_renderplan_replan.py
  - tests/test_schema_history.py
  - tests/test_schema_registry.py
  - tests/test_schema_v6_source.py
  - tests/test_schema_v7.py
  - tests/test_toml_format.py
  - utterplan/__init__.py
  - utterplan/cli.py
  - utterplan/exceptions.py
  - utterplan/model.py
  - utterplan/serialization.py
  - utterplan/toml_codec.py
  - utterplan/versioning.py
issues: []
prs: []
sources:
  - git:50dd54d4a3670cd9ca05cf3190c6f4b2f1330b9f
contributors:
  - "@holgern"
breaking: false
internal: false
order: 13
---
