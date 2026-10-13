---
schema_version: 4
id: content-0006
kind: content
type: section
section: runtime_view
title: Runtime View
order: 60
status: accepted
version: 2
body_format: markdown
---

## Scenario: compile one document

`utterplan compile` (or `compile_document` in Python) runs the full pipeline and
persists one deterministic plan. With `--trace PATH`, an optional provenance
sidecar is written next to it; `explain --trace PATH` and `inspect-trace` read that
sidecar separately from the plan.

```text
SSMD source / plain text + config
    -> parse -> source analysis -> preparation -> mapping/spoken analysis
    -> segmentation/boundaries -> flow projection
    -> FlowPlan v7 (.utterplan.toml) + optional diagnostics (+ optional trace sidecar)
```

## Scenario: incremental batch compile

`compile-many` orchestrates independent source documents in order. Each successful
FlowPlan is validated and atomically saved before the next source is processed;
ordinary failures are reported and later inputs continue unless fail-fast is
requested. Its TOML report is operational data, not a FlowPlan.

## Scenario: book compile

```text
SSMDBook manifest + chapter source
    -> utterplan compile-book
    -> independent FlowPlans in utterplan/
```

`compile-book` reads the manifest and selected chapter source to produce each
canonical semantic FlowPlan under `utterplan/` plus a `compile-report.toml`. It
never modifies the manifest or chapter files.

## Scenario: book render projection

```text
saved FlowPlans + one RenderProfile
    -> utterplan render-book (existing RenderPlan projection)
    -> profile-specific RenderPlans in renderplan/<label>--<profile-id-prefix>/
       + UtterPlan-owned renderplan-set.toml and render-report.toml
```

`render-book` does not re-read chapter content: it loads already saved plans,
projects each independently through the existing `build_render_plan()` path, and
records successful chapter identities in the variant-local `renderplan-set.toml`.
Variant directories include a readable label and a prefix of the canonical profile
ID; the profile snapshot and strict set validation prevent mixing profiles or
adopting unindexed output. RenderProfile + RenderPlan sets then flow to VoiceRender
for validation, preflight, G2P, synthesis, and audio — all outside UtterPlan.

## Scenario: load a saved plan

```text
current plan:
.utterplan.toml -- TOML decode / schema-v7 validation --> FlowPlan --> downstream chunk/pause choices --> consumer

legacy saved plan:
schema-v1–v6 saved plan -- historical reader / data-only chain --> v6; v6-to-v7 promotion refuses with recompile-required
```

Normal load/decode and execution paths reject non-v7 schemas with
`schema.version_unsupported` and direct users to recompile. `FlowPlan.load()`
accepts TOML only and rejects JSON.

## Scenario: deterministic replan refinement

`render-plan --previous-plan`/`build_render_plan(..., previous_plan=..., preflight=...)` refine only failed speech occurrences. Both the exact previous
RenderPlan and its matching preflight report are required together; UtterPlan does
not calculate renderer-specific metrics.
