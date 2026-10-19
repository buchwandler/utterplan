---
schema_version: 4
id: content-0003
kind: content
type: section
section: context_and_scope
title: Context and Scope
order: 30
status: accepted
version: 3
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
Readio / VoiceRender / other FlowPlan consumers
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
  projection; **VoiceRender** creates engine-backed profiles and owns runtime
  validation, preflight, and speech execution; **Readio** and other consumers
  consume FlowPlan downstream.

## In scope

- One document (SSMD 0.9, or explicitly selected plain text) to one executable,
  deterministic FlowPlan v7.
- Written-to-spoken preparation via TTSReady (plain text) or the SSMD-authoritative
  preparer (SSMD).
- Canonical segmentation, safe-boundary inventory, authored pause intents, typed
  directives, and markers.
- Optional provenance trace sidecars and renderer-neutral diagnostics.
- SSMDBook chapter discovery and per-file orchestration (`compile-book`,
  `render-book`) without changing manifest or chapter content.
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

## SSMDDoc source workspace

- An editable `.ssmdoc` directory is discovered by its `ssmdconvert.document` v1 manifest, not by its directory suffix. Its canonical `document.ssmd.md` is the current compiler input.
- The workspace remains one document to one FlowPlan. Manifest digests are provenance only for editable directories: UtterPlan compiles current content and never refreshes the manifest or edits the source.
- `compile-document` is single-document convenience, not book orchestration. ZIP bundles, fake chapters, and an `ssmdconvert` runtime dependency are outside the contract.
