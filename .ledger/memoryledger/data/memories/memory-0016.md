---
id: memory-0016
kind: rule
title: SSMDBook orchestration
status: accepted
priority: 100
scope: global
scope_path: ""
render_target: root_agents
source: cli
created_version: 18
modified_version: 40
tags: []
origin: ""
origin_hash: ""
section: ""
evidence:
  - kind: user_approval
    title: Review approval
    uri: memory:memory-0016#review-v35
    excerpt:
      rebuilt from current docs/architecture.md, versioning.py, and pyproject.toml
      (schema v7, RenderPlan, SSMDBook)
    content_hash: ""
    line_start: null
    line_end: null
    timestamp: ""
---

Bundle commands accept only a canonical <name>.ssmd-bundle/ root and select book or document behavior from manifest.json. Book items are selected by manifest source_number and produce independent plans; document bundles contain one item and support only the all selector. Compilation, RenderPlan projection, and replan leave manifests and source content unchanged and never create a book-level combined plan.
