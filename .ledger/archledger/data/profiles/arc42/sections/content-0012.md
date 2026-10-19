---
schema_version: 4
id: content-0012
kind: content
type: section
section: glossary
title: Glossary
order: 120
status: accepted
version: 3
body_format: markdown
---

| Term             | Meaning                                                                                                                                                                                             |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FlowPlan         | The current v7 executable speech plan: ordered FlowUnits with segments, boundaries, pause intents, directives, markers, and portable document metadata.                                             |
| FlowUnit         | A fixed paragraph-local block in `FlowPlan.flow`; not a renderer chunk.                                                                                                                             |
| FlowSegment      | One ordered segment inside a FlowUnit: prepared text, effective language, local tokens, optional replacement views, boundary arrays, pause intents, directives, markers, optional heading metadata. |
| Boundary         | A canonical safe cut opportunity (clause, sentence, paragraph, parenthetical, voice-change) independent of authored pause intent.                                                                   |
| PauseIntent      | An authored SSMD break projected to a segment edge; exact timed breaks remain exact. Renderers choose native, automatic, or manual realization.                                                     |
| Directive        | A renderer-neutral typed value resolved from SSMD scopes and voice defaults; never a concrete engine voice.                                                                                         |
| Marker           | An SSMD-authored event carried on the flow; data only.                                                                                                                                              |
| Prepared text    | The written-to-spoken segment text produced by preparation; token and replacement offsets index this text.                                                                                          |
| Replacement view | Compact preparation provenance for a segment (for example, `A R T` from `ART`); spans are local to the prepared segment text.                                                                       |
| PlanSource       | The v7 record storing the exact raw input once, optionally.                                                                                                                                         |
| Trace            | Optional versioned TOML sidecar with coordinate maps, preparation provenance, diagnostics, and renderability evidence; never part of plan identity.                                                 |
| Coordinate space | The documented space an offset indexes (source vs prepared vs segment-local). See the [coordinate-space contract](coordinate-spaces).                                                               |
| SSMD             | The 0.9 source document format; UtterPlan accepts 0.9 only.                                                                                                                                         |
| TTSReady         | Package owning reusable written-to-spoken preparation and the direct Spokenform integration.                                                                                                        |
| Spokenform       | Written-to-spoken normalization library used by TTSReady; production UtterPlan code does not import it.                                                                                             |
| PhraseSplit      | Advisory sentence-boundary proposal provider; UtterPlan validates proposals and owns canonical spans.                                                                                               |
| RenderPlan       | Shared renderer-specific plan contract produced by optional projection from a schema-v7 FlowPlan.                                                                                                   |
| RenderProfile    | A separate renderer configuration; UtterPlan loads shared data without importing VoiceRender.                                                                                                       |
| VoiceRender      | Consumer that creates engine-backed profiles and owns validation, preflight, G2P, synthesis, and audio.                                                                                             |
| SSMDBook         | Editable book workspace whose manifest drives chapter discovery; `compile-book`/`render-book` orchestrate per-file workspaces without changing content.                                             |
| Planning attempt | Inspect-only `utterplan.planning-attempt.v1` artifact for reviewing blocked renderability outcomes; never a canonical plan.                                                                         |
| plan_id          | Deterministic renderer-independent plan identity; v7 `utterplan-flow-v3` includes boundaries and never hashes TOML formatting.                                                                      |

| SSMDDoc | Editable single-document workspace using the `ssmdconvert.document` v1 manifest; `compile-document` compiles the current canonical SSMD file to one FlowPlan without mutating source. |
