---
schema_version: 4
id: content-0003
kind: content
type: section
section: context_and_scope
title: Context and Scope
order: 30
status: accepted
version: 5
body_format: markdown
---

## External context

Dependency layering (each component uses the dependency above it):

```text
Spokenform
    ^
TTSReady
    ^
UtterPlan
    ^
Downstream FlowPlan consumers
```

UtterPlan depends directly on SSMD, PhraseSplit, and TTSReady:

- **SSMD** supplies the 0.9 document format, version header, and annotation
  semantics. UtterPlan does not parse SSMD 0.8 or migrate source; older documents
  must first be converted with `ssmd migrate FILE --to 0.9`.
- **TTSReady** owns reusable written-to-spoken preparation and the direct Spokenform
  integration; production UtterPlan code does not import Spokenform.
- **PhraseSplit** supplies advisory sentence-boundary proposals; UtterPlan validates
  them and owns the canonical spans.
- **spaCy** optionally enriches tokens (best effort, `sm`/`md`/`lg`/`trf` preference;
  UtterPlan never downloads models and falls back to deterministic tokens).
- **RenderPlan** defines the shared profile/plan contract used by the optional
  projection; downstream renderers consume portable RenderProfiles and RenderPlans,
  while other downstream consumers consume FlowPlans. Engine selection, preflight,
  and speech execution are outside UtterPlan.

## In scope

- One document (SSMD 0.9, or explicitly selected plain text) to one executable,
  deterministic FlowPlan v7.
- Written-to-spoken preparation via TTSReady (plain text) or the SSMD-authoritative
  preparer (SSMD).
- Canonical segmentation, safe-boundary inventory, authored pause intents, typed
  directives, and markers.
- Optional provenance trace sidecars and renderer-neutral diagnostics.
- Manifest-driven book/document bundle dispatch through the unified `bundle` commands,
  using only canonical `.ssmd-bundle/` roots and leaving source content unchanged.
- Optional RenderPlan projection and deterministic replan refinement for stored
  schema-v7 plans.

## Out of scope

- G2P, phoneme production, model token IDs, synthesis, and audio composition.
- Fetching media or executing extension handlers; audio references and extension
  names are data only.
- Book-level semantic plans or any combined book plan.
- SSMD source migration (`ssmd migrate` owns that).
- Renderer chunking, token-budget, and pause-realization choices.
- Consumer-specific compatibility testing.

## Manifest-driven bundle inputs

- Bundle commands accept only a canonical `<name>.ssmd-bundle/` root with a
  `manifest.json`; the format field selects book or document behavior.
- Book manifests map source-numbered chapters to independent FlowPlans and support
  manifest-ordered selection.
- Document manifests map one SSMD 0.9 source to one FlowPlan and accept only the
  `all` selector.
- Both kinds use the shared `bundle compile`, `bundle render`, and `bundle replan` lifecycle. Manifest digests remain provenance; current source content is
  compiled without modifying the manifest or source files.
