---
id: memory-0004
kind: rule
title: Schema contract
status: accepted
priority: 100
scope: global
scope_path: ""
render_target: root_agents
source: cli
created_version: 6
modified_version: 23
tags: []
origin: ""
origin_hash: ""
section: ""
evidence:
  - kind: user_approval
    title: Review approval
    uri: memory:memory-0004#review-v23
    excerpt:
      rebuilt from current docs/architecture.md, versioning.py, and pyproject.toml
      (schema v7, RenderPlan, SSMDBook)
    content_hash: ""
    line_start: null
    line_end: null
    timestamp: ""
---

`.utterplan.toml` schema v7 is the current inter-package contract; schema-v5/v6 TOML and historical JSON schemas v1–v4 remain sequential migration inputs only, and only the current schema version is natively supported.
