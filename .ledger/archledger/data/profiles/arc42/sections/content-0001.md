---
schema_version: 4
id: content-0001
kind: content
type: section
section: introduction_and_goals
title: Introduction and Goals
order: 10
status: accepted
version: 3
body_format: markdown
---

UtterPlan is the canonical, engine-independent semantic compiler from one SSMD 0.9
document (or explicitly selected plain-text document) to an executable speech plan.
It owns document parsing, language runs, source linguistic analysis, SSMD annotation
meanings, coordinate mapping, spoken-text analysis, segmentation, canonical boundary
opportunities, authored pause intent, directives, and FlowPlan construction. It uses
TTSReady for reusable written-to-spoken preparation and stops before G2P, synthesis,
and audio.

## Quality goals

| Goal                                              | Motivation                                                                                                                                         |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Deterministic, renderer-independent plans         | The same source and configuration always produce the same executable plan and `plan_id`, so consumers can cache, compare, and verify plans safely. |
| Safe boundaries and authored pauses stay separate | Downstream renderers keep full freedom for chunking and pause realization without changing plan semantics.                                         |
| Portable, file-roundtrippable persistence         | `.utterplan.toml` is the single interchange format; no semantic state exists outside serialized data.                                              |
| Engine independence                               | Core code never imports synthesis engines, G2P packages, model runtimes, or audio libraries.                                                       |
| Sequential data-only migration                    | Every supported older schema has an explicit, deterministic path to the current contract.                                                          |

## Pipeline overview

```text
SSMD / plain text
       |
       v
UtterPlan parsing + language runs + source analysis
       | provider-neutral token hints + protected spans + explicit profile
       v
TTSReady.prepare_run() -> Spokenform normalization
       |
       v
UtterPlan mapping + spoken analysis + canonical segmentation + boundaries + authored pauses
       |
       v
FlowPlan v7 (paragraph-local units, segments, boundaries, authored pauses)
       |
       v
Downstream chunking / token-budget / pause choices
       |
       v
Readio / VoiceRender / other FlowPlan consumers
       |
       v
G2P / synthesis / audio (downstream)
```

The compiler still handles one document at a time; the CLI's explicit SSMDBook
commands (`compile-book`, `render-book`) discover chapters and orchestrate per-file
workspaces without changing book content.

## Document workspaces

An editable `ssmdconvert.document` v1 workspace (`.ssmdoc`) is another source path for the one-document compiler. `compile-document` discovers its canonical current SSMD document and writes one FlowPlan plus an operational report under `.readio/utterplan/`; it does not create a book or alter workspace source material.
