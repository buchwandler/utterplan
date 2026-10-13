---
id: memory-0002
kind: rule
title: Engine independence
status: accepted
priority: 100
scope: global
scope_path: ""
render_target: root_agents
source: cli
created_version: 3
modified_version: 4
tags: []
origin: ""
origin_hash: ""
section: ""
evidence:
  - kind: user_approval
    title: Review approval
    uri: memory:memory-0002#review-v4
    excerpt: verified against docs/architecture.md engine-independence constraint
    content_hash: ""
    line_start: null
    line_end: null
    timestamp: ""
---

UtterPlan is engine-independent. Core code must not import PyKokoro, PiperSynth, kokorog2p, piperg2p, ONNX Runtime, audio packages, or any consumer package.
