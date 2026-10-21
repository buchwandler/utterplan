---
schema_version: 4
id: content-0006
kind: content
type: section
section: runtime_view
title: Runtime View
order: 60
status: accepted
version: 5
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

## Scenario: compile from a bundle

```text
canonical <name>.ssmd-bundle/ + manifest.json + selected source items
    -> utterplan bundle compile
    -> one independent schema-v7 FlowPlan per selected item
       + compile-report.toml under utterplan/
```

The manifest format determines book or document behavior. Book selectors use
manifest source numbers and retain manifest order; a document bundle contains one
item and accepts only the `all` selector. Current source content is authoritative;
UtterPlan never refreshes the manifest or modifies source files.

## Scenario: bundle RenderPlan projection

```text
saved FlowPlans + explicit RenderProfile
    -> utterplan bundle render
    -> profile-specific RenderPlans under renderplan/<label>--<profile-fingerprint>/
       + profile snapshot + report + book collection index when applicable
```

Rendering reads saved plans only. Profile identity and role coverage are checked
before outputs are written. VoiceRender owns downstream preflight, G2P, synthesis,
and audio; UtterPlan remains engine-independent.

## Scenario: bundle replan refinement

```text
active RenderPlan(s) + matching VoiceRender preflight feedback
    -> utterplan bundle replan
    -> deterministic child RenderPlan(s) + selected active-reference updates
```

Replanning requires the stored profile snapshot and feedback matching the exact
active plan. Parent RenderPlans, source FlowPlans, profile identity, and unselected
active references remain unchanged. A dry run validates and reports proposed
children without changing active state.

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
