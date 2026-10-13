---
id: memory-0017
kind: rule
title: RenderPlan projection scope
status: accepted
priority: 100
scope: global
scope_path: ""
render_target: root_agents
source: cli
created_version: 19
modified_version: 36
tags: []
origin: ""
origin_hash: ""
section: ""
evidence:
  - kind: user_approval
    title: Review approval
    uri: memory:memory-0017#review-v36
    excerpt:
      rebuilt from current docs/architecture.md, versioning.py, and pyproject.toml
      (schema v7, RenderPlan, SSMDBook)
    content_hash: ""
    line_start: null
    line_end: null
    timestamp: ""
---

RenderPlan projection is optional: VoiceRender creates and validates engine-backed RenderProfiles, while UtterPlan projects stored schema-v7 FlowPlans into profile-specific RenderPlans (with `renderplan-set.toml` and reports) and performs deterministic replan refinement only.
