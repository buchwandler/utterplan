---
id: memory-0015
kind: rule
title: SSMD 0.9 source contract
status: accepted
priority: 100
scope: global
scope_path: ""
render_target: root_agents
source: cli
created_version: 17
modified_version: 34
tags: []
origin: ""
origin_hash: ""
section: ""
evidence:
  - kind: user_approval
    title: Review approval
    uri: memory:memory-0015#review-v34
    excerpt:
      rebuilt from current docs/architecture.md, versioning.py, and pyproject.toml
      (schema v7, RenderPlan, SSMDBook)
    content_hash: ""
    line_start: null
    line_end: null
    timestamp: ""
---

UtterPlan parses SSMD 0.9 only; it does not parse SSMD 0.8 or migrate source documents (`ssmd migrate` owns that).
