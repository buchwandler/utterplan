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
modified_version: 35
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

Book commands (`compile-book`, `render-book`) read the SSMDBook manifest only for chapter discovery, never modify the manifest or source chapters, write derived plans to separate directories, and never build book-level combined plans.
