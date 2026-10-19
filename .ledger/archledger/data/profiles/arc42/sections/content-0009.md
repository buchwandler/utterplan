---
schema_version: 4
id: content-0009
kind: content
type: section
section: architecture_decisions
title: Architecture Decisions
order: 90
status: accepted
version: 3
body_format: markdown
---

- **AD: SSMD 0.9 only.** The document parser calls SSMD with `dialect="0.9"` for
  every SSMD source, including unversioned fragments selected with
  `document_format="ssmd"`. UtterPlan does not parse 0.8 or migrate source; source
  conversion belongs to `ssmd migrate`. _Rationale:_ one canonical input dialect;
  `utterplan migrate` stays a serialized-plan operation.
- **AD: Format-dependent preparation.** Preparation `auto` resolves after the input
  format is known — plain text goes through TTSReady/Spokenform, SSMD goes through
  the SSMD-authoritative preparer applying reviewed `sub` aliases exactly once.
  _Rationale:_ SSMD annotations must be applied exactly once and authoritatively;
  plain text reuses the shared written-to-spoken machinery.
- **AD: Boundaries are separate from authored pauses.** Safe clause, sentence,
  paragraph, parenthetical, and voice-change opportunities are carried as boundary
  kinds independently of authored `PauseIntent` values; both may coexist at one
  edge. UtterPlan neither activates automatic pauses nor invents durations.
  _Rationale:_ renderers keep native, automatic, or manual realization freedom
  without recompilation.
- **AD: Boundaries participate in v7 identity.** The v7 `utterplan-flow-v3`
  `plan_id` includes the boundary inventory; v5/v6 keep their historical hash
  schemas. _Rationale:_ boundaries are executable facts, so identity must cover
  them.
- **AD: v6-to-v7 migration refuses.** The step returns
  `migration.recompile_required`. _Rationale:_ serialized v6 semantics cannot prove
  a complete boundary inventory; guessing would corrupt the safety contract.
- **AD: TOML-only persistence.** Current plans persist as deterministic
  `.utterplan.toml`; `FlowPlan.load()` accepts TOML only and rejects JSON.
  Historical JSON Schema resources for v1–v4 stay frozen and immutable.
  _Rationale:_ one portable interchange format; strict load rejects ambiguity.
- **AD: Traces are sidecars.** Optional compiler traces carry source text/hash,
  coordinate maps, preparation provenance, diagnostics, and renderability evidence
  in a separate versioned TOML. _Rationale:_ provenance must never alter executable
  content or identity.
- **AD: One document, one plan; books are orchestration.** `compile-book` and
  `render-book` compose per-file operations without a combined book-level semantic
  plan and never modify the manifest or chapters. _Rationale:_ keeps the engine-
  independent boundary intact and chapter plans canonical.
- **AD: Best-effort spaCy with deterministic fallback.** Models are preferred in
  `sm`/`md`/`lg`/`trf` order when already installed and never downloaded; without
  spaCy, planning continues with deterministic fallback tokens. _Rationale:_
  reproducibility and offline safety outweigh always-on enrichment.
- **AD: Package and schema versions are independent.** Migration preserves a
  compiled plan; replanning is a separate operation. _Rationale:_ schema evolution
  must not force package-version coupling or silent replans.

- **AD: SSMDDoc is one document, not a book.** An `ssmdconvert.document` v1 workspace resolves to its current canonical SSMD source and the existing one-document compiler, producing one FlowPlan. Editable directory digests do not override current source content; UtterPlan neither refreshes nor mutates the workspace. _Rationale:_ preserve one-document/one-plan semantics and keep source-workspace ownership in `ssmdconvert`.
