---
schema_version: 4
id: content-0004
kind: content
type: section
section: solution_strategy
title: Solution Strategy
order: 40
status: accepted
version: 10
body_format: markdown
source_refs:
  - path: utterplan/prepared_semantics.py
    role: implements
    reason: Strict replacement-derived character-spelling annotations.
  - path: utterplan/planner.py
    role: implements
    reason: Applies derived annotations before segmentation.
  - path: utterplan/flow_projection.py
    role: implements
    reason: Projects exact prepared semantic spans into segments.
  - path: tests/test_prepared_semantics.py
    role: validates
    reason: Matcher and annotation augmentation regression coverage.
  - path: tests/test_ssmd_substitution_preparation.py
    role: validates
    reason: SSMD replacement behavior coverage.
  - path: docs/python-api.md
    role: documents
    reason: Public character-spelling semantics and renderer boundary.
  - path: tests/test_replacement_provenance.py
    role: validates
    reason: Verifies replacement provenance remains unchanged by semantic derivation.
---

UtterPlan follows a strict stage pipeline in which every stage produces plain,
serializable data:

1. **Parse.** The document parser calls SSMD with `dialect="0.9"` for every SSMD
   source path, including unversioned fragments selected with
   `document_format="ssmd"`. Plain-text input is explicit and always requires a
   language fallback; SSMD header language is authoritative over a fallback and a
   fallback never rewrites document semantics.
2. **Analyze source.** Provider-neutral token hints, protected spans, and an
   explicit linguistic profile are produced; spaCy enrichment is best effort with a
   deterministic fallback.
3. **Prepare.** Preparation `auto` resolves after the input format is known: plain
   text uses TTSReady/Spokenform, while SSMD uses the SSMD-authoritative preparer to
   apply reviewed `sub` aliases exactly once. SSMD compilation in this mode does not
   call Spokenform; explicit `spokenform` remains an opt-in legacy path and emits a
   warning.
4. **Map and re-analyze.** UtterPlan maps prepared spoken text back onto source
   coordinates and runs spoken-text analysis.
5. **Segment and bound.** Paragraph events, validated sentence proposals
   (PhraseSplit), language/directive/pause/marker/media cuts, and atomic media-span
   protection produce the canonical span and boundary inventory.
6. **Project.** Flow projection assembles paragraph-local `FlowUnit` objects with
   ordered `FlowSegment` records, segment-local tokens, replacement views, boundary
   arrays, and pause intents, guarded by a token-edge coverage check as defense in
   depth.

Supporting tactics:

- **Engine independence by construction.** The dependency direction is
  `PyKokoro or another renderer -> UtterPlan`; import-boundary tests keep engine,
  G2P, runtime, audio, and consumer packages out of core code.
- **Determinism by default.** Fixed orderings, no wall-clock or environment inputs
  in defaults, and identity hashing that never hashes TOML formatting.
- **Safety separation.** Canonical safe-boundary opportunities and authored pause
  intents are distinct facts that may coexist at one edge; renderers realize them
  independently.
- **Data-only evolution.** Registered migration steps walk serialized plain data
  through v1 -> v2 -> v3 -> v4 -> v5 -> v6 and intentionally refuse the v6-to-v7
  step (`migration.recompile_required`) because legacy data cannot prove a complete
  boundary inventory.
- **Sidecar provenance.** Detailed diagnostics, coordinate maps, and renderability
  evidence live in an optional versioned trace TOML that never affects plan
  identity or executable content.

## Prepared character-spelling semantics

After written-to-spoken preparation and before segmentation, UtterPlan inspects verified replacement records for the exact character-spelling transformation: an ASCII uppercase-letter/digit core of at least two characters becomes the same characters joined by single spaces, optionally retaining an identical `'s` or `’s` suffix. This derives a compiler-owned `say_as=characters` annotation over only the prepared character core. For example, `[ART]{sub=\"A R T\"}` keeps prepared text `A R T`; `[ART's]{sub=\"A R T's\"}` keeps `A R T's` and marks only `A R T`.

The derivation is portable executable intent, not a renderer-specific spelling rewrite. Prepared text never becomes `A- R- T`; a renderer adapter may choose that frontend form. Existing semantic-edge segmentation produces the exact controlled span, while RenderPlan sentence grouping retains the full sentence as one normal speech request with a request-local control. This feature adds neither a sentence split nor an automatic pause.

Authored `say-as` semantics take precedence, and the consumed SSMD `sub` annotation remains consumed. The derived directive uses existing schema-v7 `SayAsDirective` serialization and identity hashing; replacement records remain diagnostic provenance and are not synthesis input. No schema version or migration changes are required.
