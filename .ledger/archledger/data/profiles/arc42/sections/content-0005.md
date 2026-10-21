---
schema_version: 4
id: content-0005
kind: content
type: section
section: building_block_view
title: Building Block View
order: 50
status: accepted
version: 4
body_format: markdown
---

UtterPlan is one Python package (`utterplan`) exposing a library API and a CLI.
Internal building blocks group as follows (module names refer to
`utterplan/<module>.py`):

| Block                       | Modules                                                                                                                                             | Responsibility                                                                                                                                                                                 |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Public entry points         | `__init__.py`, `cli.py`, `__main__.py`                                                                                                              | `compile_document`, `UtterancePlanner`, `FlowPlan`, `build_render_plan`, `preview_plan`; the `utterplan` command.                                                                              |
| Public entry points         | `__init__.py`, `cli.py`, `__main__.py`                                                                                                              | `compile_document`, `compile_bundle`, `render_bundle`, `replan_bundle`, `UtterancePlanner`, `FlowPlan`, `build_render_plan`, `preview_plan`; the `utterplan` command.                          |
| Document parsing            | `parsers.py`, `stages/document/plain.py`, `stages/document/ssmd.py`                                                                                 | SSMD 0.9 and explicit plain-text document events (paragraphs, annotations, media spans).                                                                                                       |
| Preparation                 | `preparation.py`, `stages/preparation/{identity,ssmd,ttsready}.py`                                                                                  | Written-to-spoken preparation: TTSReady/Spokenform for plain text, SSMD-authoritative `sub` application for SSMD, exact-once semantics.                                                        |
| Linguistic analysis         | `linguistics.py`, `spacy_models.py`, `language.py`                                                                                                  | Best-effort spaCy enrichment with deterministic fallback, model-tier preference, language resolution.                                                                                          |
| Segmentation and boundaries | `segmentation.py`, `token_topology.py`, `boundaries.py`, `spans.py`, `units.py`                                                                     | Paragraph/sentence/part topology, advisory proposal validation, atomic media-span protection, canonical boundary inventory.                                                                    |
| Semantics                   | `pauses.py`, `directives.py`                                                                                                                        | Authored `PauseIntent` values, renderer-neutral typed directives, markers.                                                                                                                     |
| Flow projection             | `flow_projection.py`                                                                                                                                | Final `FlowUnit`/`FlowSegment` assembly with token-edge coverage checks.                                                                                                                       |
| Plan model and identity     | `model.py`, `hashing.py`, `versioning.py`, `units.py`                                                                                               | Immutable FlowPlan v7 objects, deterministic `plan_id`, schema/version facts.                                                                                                                  |
| Persistence                 | `toml_codec.py`, `codecs/{v4,v5,v6,v7}_toml.py`, `serialization.py`, `schema_registry.py`, `atomic_io.py`, `format.py`                              | `.utterplan.toml` write/read, migration-only historical codecs, atomic file IO, strict validation.                                                                                             |
| Migration                   | `migration.py`, `migrations/registry.py`, `migrations/v1_to_v2.py` … `v6_to_v7.py`                                                                  | Data-only sequential migration chain with recompile-required refusal at v6-to-v7.                                                                                                              |
| RenderPlan projection       | `renderplan_projection.py`, `renderplan_grouping.py`, `renderplan_export.py`, `renderplan_replan.py`                                                | Optional schema-v7 FlowPlan to shared RenderPlan projection and deterministic replan refinement.                                                                                               |
| Bundle orchestration        | `ssmd_bundle.py`, `bundle.py`, `bundle_replan.py`, `_book_service.py`, `_book_replan.py`, `_document_service.py`, `batch.py`, `renderplan_batch.py` | Manifest-driven book/document compilation, profile projection, and replan refinement through the unified bundle API and CLI; one FlowPlan per source item.                                     |
| Diagnostics and explanation | `diagnostics.py`, `explain.py`, `preview.py`, `progress.py`, `renderability.py`, `attempts.py`, `attempt_serialization.py`, `trace_codec.py`        | Renderer-neutral diagnostics, human-readable speech-plan explanation, chunk previews, typed progress events, renderability repair policy, inspect-only planning attempts, trace sidecar codec. |

The public boundary includes `compile_document`, `compile_bundle`, `render_bundle`,
`replan_bundle`, `UtterancePlanner`, `FlowPlan`, `build_render_plan`, `preview_plan`,
and the CLI. Bundle loading, kind-specific adapters, and callbacks are exposed only
where required by the unified integration contract; compiler machinery otherwise
remains private. Compiler-only normalized graph state stays private; when requested,
the trace retains source text/hash, coordinate maps, preparation provenance,
diagnostics, and renderability evidence in a separate versioned TOML sidecar. Trace
state is not renderer input and does not affect plan identity or TOML.

## Bundle orchestration

`ssmd_bundle.py` loads and validates canonical `.ssmd-bundle/` roots, dispatches
from `manifest.json`, normalizes item selection, and enforces path containment.
`bundle.py` and `bundle_replan.py` expose uniform compile, render, and replan
services; private book and document helpers retain kind-specific persistence and
report behavior. The generic source loader remains limited to standalone files.
