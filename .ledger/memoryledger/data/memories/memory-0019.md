---
id: memory-0019
kind: rule
title: Self-contained tests
status: accepted
priority: 100
scope: global
scope_path: ""
render_target: root_agents
source: cli
created_version: 21
modified_version: 38
tags: []
origin: ""
origin_hash: ""
section: ""
evidence:
  - kind: user_approval
    title: Review approval
    uri: memory:memory-0019#review-v38
    excerpt:
      rebuilt from current docs/architecture.md, versioning.py, and pyproject.toml
      (schema v7, RenderPlan, SSMDBook)
    content_hash: ""
    line_start: null
    line_end: null
    timestamp: ""
---

Repository tests must be self-contained and must not require sibling consumer checkouts; consumer-specific compatibility testing belongs in the consumer repository.
