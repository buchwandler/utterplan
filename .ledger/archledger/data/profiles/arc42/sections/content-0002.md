---
schema_version: 4
id: content-0002
kind: content
type: section
section: architecture_constraints
title: Architecture Constraints
order: 20
status: accepted
version: 2
body_format: markdown
---

The following constraints are binding development rules for UtterPlan and are
enforced by tests where possible.

- **Engine independence.** Core code must not import PyKokoro, PiperSynth,
  kokorog2p, piperg2p, ONNX Runtime, audio packages, or any consumer package.
- **UtterPlan ends before G2P.** Engine/model selection, synthesis, and audio
  composition happen downstream.
- **Public plan purity.** Public FlowPlan objects contain no phonemes, model token
  IDs, models, sessions, or audio. Completed plans must not retain spaCy or
  provider documents.
- **Schema contract.** `.utterplan.toml` schema v7 is the current inter-package
  contract. Schema-v5/v6 TOML and historical JSON schemas v1–v4 remain sequential
  migration inputs only.
- **Roundtrip survivability.** Python objects may not contain semantic state that
  cannot survive file roundtrip.
- **Coordinate discipline.** Every offset has a documented coordinate space (see
  the [coordinate-space contract](coordinate-spaces)).
- **Deterministic defaults.** Default planning is deterministic.
- **Schema governance.** Schema changes require explicit compatibility review,
  frozen historical fixture coverage, deterministic migration tests, and package
  artifact checks. Released schema files are immutable and retained under versioned
  paths; schemas v5, v6, and v7 have no JSON Schema resources.
- **Data-only migrations.** Migrations operate on serialized plain data and may not
  call parser, planner, G2P, renderer, or audio stages.
- **Version independence.** Package version and schema version remain independent.
  Migration preserves a compiled plan; replanning is a separate operation.
- **Trace isolation.** Optional compiler traces are sidecars; they must never alter
  executable plan content or identity.
- **Self-contained tests.** Repository tests must not require sibling consumer
  checkouts; consumer-specific compatibility testing belongs in the consumer
  repository.
