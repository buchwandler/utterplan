# Architecture

UtterPlan is an engine-independent compiler from one SSMD document (or explicitly selected plain-text document) to an executable speech plan. It owns document parsing, language runs, source linguistic analysis, SSMD annotation meanings, coordinate mapping, spoken-text analysis, segmentation, canonical boundary opportunities, authored pause intent, directives, and FlowPlan construction. It uses TTSReady for reusable written-to-spoken preparation and stops before G2P, synthesis, and audio. The compiler still handles one document at a time; the CLI's explicit SSMDBook commands discover chapters and orchestrate per-file workspaces without changing book content.

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

UtterPlan depends directly on SSMD, PhraseSplit, and TTSReady. TTSReady owns the direct Spokenform integration; production UtterPlan code does not import Spokenform. Readio, VoiceRender, and other consumers consume FlowPlan and may perform downstream G2P, synthesis, and audio work. UtterPlan must not depend on those consumer or engine packages, model runtimes, or audio libraries. UtterPlan's `compile-book` and `render-book` CLI commands provide safe SSMDBook chapter discovery and per-file orchestration; they do not introduce a book-level semantic plan or modify source chapters.

## Compiler and public plan boundary

`compile_document` returns a `CompileResult` containing the current immutable `FlowPlan`, renderer-independent diagnostics, and an optional `PreparationTrace`. `UtterancePlanner.plan` also returns `FlowPlan`. Compiler-only normalized graph state remains private. When requested, the trace retains source text/hash, coordinate maps, preparation provenance, diagnostics, and renderability evidence in a separate versioned TOML sidecar. Trace state is not renderer input and does not affect plan identity or TOML.

`FlowPlan` is the current v7 executable contract: ordered `FlowUnit` objects each own ordered `FlowSegment` records. Segments include prepared text, effective language, local tokens with authoritative linguistic facts, optional compact replacement views, canonical safe-boundary arrays, authored semantic pause intents, directives, markers, and optional heading metadata. Replacement spans are local to the final prepared segment text; full source maps remain in the optional trace. `DocumentInfo` retains compact portable document information; `LinguisticProvenance` identifies providers without retaining their documents. UtterPlan ends before G2P. Engine/model selection, synthesis, and audio composition happen downstream.

## Compiler-owned segmentation topology

Segmentation has four distinct layers: parser-owned paragraph events define paragraph regions; PhraseSplit supplies advisory sentence-boundary proposals; UtterPlan validates those proposals and owns canonical paragraph, sentence, and private sentence-part spans in prepared spoken-text coordinates; language, directive, authored-pause, marker, and media cuts subdivide a part into final segments. Positive-width atomic media spans protect their interiors from automatic sentence/part boundaries; zero-width media events remain renderer operations, not parts. The public v7 `FlowPlan` contains only the resulting compact ordered flow—there is no serialized sentence-parts table.

PhraseSplit failure or an invalid proposal batch falls back to deterministic, conservative terminal scanning. Unsafe automatic cuts inside provider-aware lexical content are merged or dropped before projection; the final flow-projection token-edge check remains defense in depth. Exact surface and non-whitespace coverage checks run before and after applicable repairs. This normalization is independent of `renderability_mode`: strict and repair compilation use the same topology, while renderability mode governs only the existing punctuation-repair policy. See the [coordinate-space contract](coordinate-spaces) for offset ownership.

## SSMD and preparation

The document parser calls SSMD with `dialect="0.9"` for every SSMD source path, including unversioned fragments selected with `document_format="ssmd"`. UtterPlan does not parse SSMD 0.8 or migrate source. Older documents must first be converted with `ssmd migrate FILE --to 0.9`. The `utterplan migrate` command imports serialized legacy plans and applies schema migrations only.

SSMD header language is authoritative over a fallback. The CLI can omit `--language` when the header declares a language; plain input always needs a fallback. A fallback never forces or rewrites document semantics.

Preparation `auto` resolves after the input format is known: plain text uses TTSReady/Spokenform, while SSMD uses the SSMD-authoritative preparer to apply reviewed `sub` aliases exactly once. SSMD compilation in this mode does not call Spokenform; explicit `spokenform` remains an opt-in legacy path and emits a warning.

Preparation creates structural and spoken representations internally. The executable FlowPlan retains prepared segment text and compact segment-local replacement views, and v7 stores the exact raw input once in its optional `PlanSource` record; it does not retain structural text or full source-to-spoken maps, parser annotations, or global compiler token tables. Detailed diagnostics and complete provenance mappings remain in an optional trace. See the [coordinate-space contract](coordinate-spaces).

## Pause and directive semantics

Authored SSMD breaks project to local `PauseIntent` values on segment edges, while safe clause, sentence, paragraph, parenthetical, and voice-change opportunities are carried separately as boundary kinds. Both facts may coexist at one edge. UtterPlan does not activate automatic pauses or invent numeric durations; downstream renderers choose native, automatic, or manual realization. Exact authored timed breaks remain exact. Ambiguous historical pause evidence fails migration rather than being guessed.

Typed directives are renderer-neutral values resolved from SSMD scopes and voice defaults. Logical voice bindings remain references, not concrete engine voices. Audio references and extension names are data only; UtterPlan does not fetch media or execute handlers.

## Identity and determinism

Plan identity is deterministic and renderer-independent. The v7 `plan_id` includes the exact UTF-8 SHA-256 digest of optional raw source, plus executable flow, canonical boundary opportunities, authored pause intents, and compact portable metadata; it never hashes TOML formatting. The v7 `utterplan-flow-v3` identity includes boundaries, while v5/v6 retain their historical hash schemas. Renderer chunk and pause strategies are not identity inputs. Trace data, provider documents, model sessions, diagnostics, producer/package version, G2P output, and audio do not define executable identity. Package version is independent of explicit plan `schema_version`.

## Persistence compatibility boundary

Current plans persist as deterministic `.utterplan.toml` files with schema v7; `FlowPlan.load()` accepts TOML only. The v7 TOML codec validates and constructs `FlowPlan`; v5/v6 codecs are migration-only and are never selected by normal loading. Normal load/decode and execution paths reject non-v7 schemas with `schema.version_unsupported` and direct users to recompile. Historical migration remains an explicit serialized-data operation; v6-to-v7 promotion requires recompiling source because legacy data cannot prove a complete boundary inventory. Schemas v5, v6, and v7 have no JSON Schema resources or JSON plan format. Frozen JSON Schema definitions for historical schemas v1–v4 remain under versioned resources.

```text
current plan:
.utterplan.toml -- TOML decode / schema-v7 validation --> FlowPlan --> downstream chunk/pause choices --> consumer

legacy saved plan:
schema-v1–v6 saved plan -- historical reader / data-only chain --> v6; v6-to-v7 promotion refuses with recompile-required
```

Migration is not planning. Registered data-only steps cover the sequential v1 -> v2 -> v3 -> v4 -> v5 -> v6 chain; the v6-to-v7 step intentionally returns `migration.recompile_required`: serialized v6 semantics cannot prove the complete boundary inventory. Every step operates on serialized plain data and does not rerun source parsing, preparation, NLP, planning, G2P, rendering, or audio processing. The v4-to-v5 projection verifies token spans and pause evidence and fails rather than guessing; v5-to-v6 preserves executable semantics and never invents unavailable source text. Downgrades are not supported.

`compile-many` orchestrates independent source documents in order. Each successful FlowPlan is validated and atomically saved before the next source is processed; ordinary failures are reported and later inputs continue unless fail-fast is requested. Its TOML report is operational data, not a FlowPlan.

## Book-level RenderPlan projection boundary

The SSMDBook workflow composes per-file operations without creating a combined
book plan or crossing UtterPlan's engine-independent boundary:

```text
SSMDBook manifest + chapter source
    -> utterplan compile-book
    -> independent FlowPlans in utterplan/

saved FlowPlans + one RenderProfile
    -> utterplan render-book (existing RenderPlan projection)
    -> profile-specific RenderPlans in renderplan/<label>--<profile-id-prefix>/
       + UtterPlan-owned renderplan-set.toml and render-report.toml

RenderProfile + RenderPlan set
    -> VoiceRender profile validation / preflight / G2P / synthesis / audio
```

`compile-book` reads the manifest and selected chapter source to produce each
canonical semantic FlowPlan. `render-book` does not re-read chapter content: it
loads already saved plans, projects each independently through the existing
`build_render_plan()` path, and records successful chapter identities in the
variant-local `renderplan-set.toml`. The index and operational report are not
RenderPlan schema objects and do not change shared RenderPlan contracts. Variant
directories include a readable label and a prefix of the canonical profile ID;
the profile snapshot and strict set validation prevent mixing profiles or adopting
unindexed output. Existing `render-plan` remains the low-level one-file projection
and deterministic refinement interface.

The profile and RenderPlan data contract belongs to [RenderPlan](https://pypi.org/project/renderplan/).
[VoiceRender](https://pypi.org/project/voicerender/) creates engine-backed profiles
and owns runtime validation, preflight, and speech execution. UtterPlan loads shared
RenderPlan data without importing VoiceRender, checking engine availability, or
invoking G2P, model runtimes, synthesis, or audio packages. Neither book command
modifies the manifest or source chapter files.
