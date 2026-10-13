---
id: memory-0018
kind: rule
title: Dependency layering
status: accepted
priority: 100
scope: global
scope_path: ""
render_target: root_agents
source: cli
created_version: 20
modified_version: 37
tags: []
origin: ""
origin_hash: ""
section: ""
evidence:
  - kind: user_approval
    title: Review approval
    uri: memory:memory-0018#review-v37
    excerpt:
      rebuilt from current docs/architecture.md, versioning.py, and pyproject.toml
      (schema v7, RenderPlan, SSMDBook)
    content_hash: ""
    line_start: null
    line_end: null
    timestamp: ""
---

UtterPlan depends directly on SSMD, PhraseSplit, TTSReady, and the renderplan contract package only; production code does not import Spokenform, and spaCy stays optional best-effort enrichment.
