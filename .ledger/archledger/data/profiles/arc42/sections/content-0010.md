---
schema_version: 4
id: content-0010
kind: content
type: section
section: quality_requirements
title: Quality Requirements
order: 100
status: accepted
version: 2
body_format: markdown
---

- **Determinism.** Default planning is deterministic. Identical source and
  configuration always produce identical executable content and `plan_id`; identity
  hashing never hashes TOML formatting and excludes renderer chunk/pause strategies,
  trace data, provider documents, diagnostics, producer version, G2P output, and
  audio.
- **Portability / roundtrip survivability.** Python objects may not contain
  semantic state that cannot survive file roundtrip. Plans reload from
  `.utterplan.toml` byte-stable; saved and loaded plans compare equal.
- **Engine independence.** Core code must not import PyKokoro, PiperSynth,
  kokorog2p, piperg2p, ONNX Runtime, audio packages, or consumer packages; the
  intended dependency direction is `renderer -> UtterPlan`, enforced by
  import-boundary and dependency-architecture tests.
- **Plan purity.** Public FlowPlan objects contain no phonemes, model token IDs,
  models, sessions, or audio; completed plans retain no spaCy or provider
  documents.
- **Robustness.** PhraseSplit failure or invalid proposal batches fall back to
  deterministic conservative terminal scanning; unsafe cuts are merged or dropped;
  exact surface and non-whitespace coverage checks run before and after repairs;
  the final token-edge check is defense in depth. Interrupted writes never leave
  partial files (atomic IO).
- **Compatibility governance.** Schema changes require explicit compatibility
  review, frozen historical fixture coverage, deterministic migration tests, and
  package artifact checks. Every supported older schema retains a sequential
  data-only migration path to current; ambiguous historical pause evidence fails
  migration rather than being guessed.
- **Testability.** The repository test suite is self-contained (golden fixtures,
  migration fixtures, schema-history fixtures, consumer-contract tests) and must
  not require sibling consumer checkouts; consumer-specific compatibility testing
  belongs in the consumer repository.
- **Operational transparency.** Renderer-neutral diagnostics always report
  failures; terminal diagnostics default to warnings with `all`/`none` overrides;
  batch and book reports retain every diagnostic; typed progress callbacks expose
  long-running planning without changing the plan.
