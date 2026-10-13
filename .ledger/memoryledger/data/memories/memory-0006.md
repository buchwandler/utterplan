---
id: memory-0006
kind: rule
title: Plan purity
status: accepted
priority: 100
scope: global
scope_path: ""
render_target: root_agents
source: cli
created_version: 8
modified_version: 25
tags: []
origin: ""
origin_hash: ""
section: ""
evidence:
  - kind: user_approval
    title: Review approval
    uri: memory:memory-0006#review-v25
    excerpt:
      rebuilt from current docs/architecture.md, versioning.py, and pyproject.toml
      (schema v7, RenderPlan, SSMDBook)
    content_hash: ""
    line_start: null
    line_end: null
    timestamp: ""
---

Public FlowPlan objects contain no phonemes, model token IDs, models, sessions, or audio; completed plans must not retain spaCy or provider documents.
