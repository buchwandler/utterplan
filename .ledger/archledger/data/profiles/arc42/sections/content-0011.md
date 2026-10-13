---
schema_version: 4
id: content-0011
kind: content
type: section
section: risks_and_technical_debt
title: Risks and Technical Debt
order: 110
status: accepted
version: 2
body_format: markdown
---

- **Historical schema surface.** Four frozen JSON Schema readers (v1–v4) plus
  schema-v5/v6 TOML migration inputs must keep working and stay immutable under
  versioned paths. Each schema change adds compatibility-review and fixture burden.
- **v6 plans cannot be promoted.** The v6-to-v7 step intentionally refuses with
  `migration.recompile_required`; owners of v6 archives must recompile from source.
- **Ambiguous legacy pause evidence fails migration.** Correct but strict: archives
  with ambiguous historical pause evidence need manual review instead of a guess.
- **spaCy environment divergence.** Best-effort enrichment means plans compiled
  with different locally installed model tiers (`sm`/`md`/`lg`/`trf`) can carry
  different token facts; the deterministic fallback is the reproducibility anchor.
  Consumers must not retokenize or rerun spaCy on v7 token views.
- **Advisory proposal dependence.** Sentence-boundary quality depends on
  PhraseSplit proposals; the conservative fallback protects correctness but may
  produce fewer, larger parts when proposals fail.
- **Renderer-side interpretation debt.** Media references, extension names, and
  logical voice bindings are data only; correctness of fetch, handler execution,
  and voice resolution rests entirely with consumers.
- **Book workflows stay per-file.** No book-level plan exists by design; any future
  cross-chapter concerns (ordering guarantees, global numbering) must remain
  orchestration-level and must not leak into chapter plans.
