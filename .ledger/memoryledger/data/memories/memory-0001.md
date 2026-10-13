---
id: memory-0001
kind: document
title: "Full migrated source: UtterPlan development rules"
status: archived
priority: 100
scope: repo
scope_path: ""
render_target: linked_doc
source: adopt
created_version: 1
modified_version: 39
tags: []
origin: adopt:AGENTS.md:full-source
origin_hash: b8b3fbf028735052763cb52be5a11f78ac1016fe2f74eb310043bb0e4ccae4c1
section: ""
evidence:
  - kind: file
    title: Original manual agent file
    uri: AGENTS.md
    excerpt: ""
    content_hash: b8b3fbf028735052763cb52be5a11f78ac1016fe2f74eb310043bb0e4ccae4c1
    line_start: null
    line_end: null
    timestamp: ""
  - kind: user_approval
    title: Review approval
    uri: memory:memory-0001#review-v2
    excerpt: load existing AGENTS.md before rebuild
    content_hash: ""
    line_start: null
    line_end: null
    timestamp: ""
---

# UtterPlan development rules

1. UtterPlan is engine-independent.
2. `.utterplan.toml` schema v6 is the current inter-package contract; schema-v5 TOML and historical JSON schemas v1–v4 remain sequential migration inputs.
3. Python objects may not contain semantic state that cannot survive file roundtrip.
4. UtterPlan ends before G2P.
5. Core code must not import PyKokoro, PiperSynth, kokorog2p, piperg2p, ONNX Runtime, or audio packages.
6. Public FlowPlan objects contain no phonemes, model token IDs, models, sessions, or audio.
7. Completed plans must not retain spaCy or provider documents.
8. Every offset has a documented coordinate space.
9. Default planning is deterministic.
10. Schema changes require explicit compatibility review.
11. Repository tests must be self-contained and must not require sibling consumer checkouts.
12. Consumer-specific compatibility testing belongs in the consumer repository.
13. Released schema files are immutable and retained under versioned paths; schemas v5 and v6 have no JSON Schema resources.
14. Every supported older schema must retain a sequential migration path to current.
15. Migrations operate on serialized plain data and may not call parser, planner, G2P, renderer, or audio stages.
16. Schema changes require frozen historical fixture coverage, deterministic migration tests, and package artifact checks.
17. Package version and schema version remain independent. Migration preserves a compiled plan; replanning is a separate operation.
18. Optional compiler traces are sidecars; they must never alter executable plan content or identity.
