# Architecture

UtterPlan is an engine-independent compiler from one SSMD document (or explicitly selected plain-text document) to an executable speech plan. It owns document parsing, language runs, source linguistic analysis, SSMD annotation meanings, coordinate mapping, spoken-text analysis, segmentation, directives, pause intent, and FlowPlan construction. It uses TTSReady for reusable written-to-spoken preparation and stops before G2P, synthesis, and audio. Consumers compile documents independently; UtterPlan does not load books or manage workspaces.

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
UtterPlan mapping + spoken analysis + segmentation + directives + pauses
       |
       v
FlowPlan (ordered units and local segments)
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

UtterPlan depends directly on SSMD, PhraseSplit, and TTSReady. TTSReady owns the direct Spokenform integration; production UtterPlan code does not import Spokenform. Readio, VoiceRender, and other consumers consume FlowPlan and may perform downstream G2P, synthesis, and audio work. UtterPlan must not depend on those consumer or engine packages, model runtimes, or audio libraries. Book iteration belongs to consumers and conversion tools.

## Compiler and public plan boundary

`compile_document` returns a `CompileResult` containing the current immutable `FlowPlan`, renderer-independent diagnostics, and an optional `PreparationTrace`. `UtterancePlanner.plan` also returns `FlowPlan`. Compiler-only normalized graph state remains private. When requested, the trace retains source text/hash, coordinate maps, preparation provenance, diagnostics, and renderability evidence in a separate versioned TOML sidecar. Trace state is not renderer input and does not affect plan identity or TOML.

`FlowPlan` is the current v6 executable contract: ordered `FlowUnit` objects each own ordered `FlowSegment` records. Segments include prepared text, effective language, local tokens with authoritative linguistic facts, optional compact replacement views, semantic pause intents, directives, markers, and optional heading metadata. Replacement spans are local to the final prepared segment text; full source maps remain in the optional trace. `DocumentInfo` retains compact portable document information; `LinguisticProvenance` identifies providers without retaining their documents. UtterPlan ends before G2P. Engine/model selection, synthesis, and audio composition happen downstream.

## Compiler-owned segmentation topology

Segmentation has four distinct layers: parser-owned paragraph events define paragraph regions; PhraseSplit supplies advisory sentence-boundary proposals; UtterPlan validates those proposals and owns canonical paragraph, sentence, and private sentence-part spans in prepared spoken-text coordinates; renderer-required language, directive, pause, marker, and media cuts subdivide a part into final segments. Positive-width atomic media spans protect their interiors from automatic sentence/part boundaries; zero-width media events remain renderer operations, not parts. The public v6 `FlowPlan` contains only the resulting compact ordered flow—there is no serialized sentence-parts table.

PhraseSplit failure or an invalid proposal batch falls back to deterministic, conservative terminal scanning. Unsafe automatic cuts inside provider-aware lexical content are merged or dropped before projection; the final flow-projection token-edge check remains defense in depth. Exact surface and non-whitespace coverage checks run before and after applicable repairs. This normalization is independent of `renderability_mode`: strict and repair compilation use the same topology, while renderability mode governs only the existing punctuation-repair policy. See the [coordinate-space contract](coordinate-spaces) for offset ownership.

## SSMD and preparation

The document parser calls SSMD with `dialect="0.9"` for every SSMD source path, including unversioned fragments selected with `document_format="ssmd"`. UtterPlan does not parse SSMD 0.8 or migrate source. Older documents must first be converted with `ssmd migrate FILE --to 0.9`. The `utterplan migrate` command imports serialized legacy plans and applies schema migrations only.

SSMD header language is authoritative over a fallback. The CLI can omit `--language` when the header declares a language; plain input always needs a fallback. A fallback never forces or rewrites document semantics.

Preparation `auto` resolves after the input format is known: plain text uses TTSReady/Spokenform, while SSMD uses the SSMD-authoritative preparer to apply reviewed `sub` aliases exactly once. SSMD compilation in this mode does not call Spokenform; explicit `spokenform` remains an opt-in legacy path and emits a warning.

Preparation creates structural and spoken representations internally. The executable FlowPlan retains prepared segment text and compact segment-local replacement views, and v6 stores the exact raw input once in its optional `PlanSource` record; it does not retain structural text or full source-to-spoken maps, parser annotations, or global compiler token tables. Detailed diagnostics and complete provenance mappings remain in an optional trace. See the [coordinate-space contract](coordinate-spaces).

## Pause and directive semantics

Authored SSMD breaks and semantic pause strengths project to local `PauseIntent` values on segment edges. The plan does not invent numeric durations or serialize an activation policy. Application pause mode controls which intents the compiler activates; consumer-specific timing policy remains downstream. Exact authored timed breaks remain exact. Ambiguous historical pause evidence fails migration rather than being guessed.

Typed directives are renderer-neutral values resolved from SSMD scopes and voice defaults. Logical voice bindings remain references, not concrete engine voices. Audio references and extension names are data only; UtterPlan does not fetch media or execute handlers.

## Identity and determinism

Plan identity is deterministic and renderer-independent. The v6 `plan_id` includes the exact UTF-8 SHA-256 digest of optional raw source, plus executable flow and compact portable metadata; it never hashes TOML formatting. Flow-unit hashes remain `utterplan-flow-v1` over local ordered segment semantics, so source-only changes do not invalidate renderer-facing unit caches. Trace data, provider documents, model sessions, diagnostics, producer/package version, G2P output, and audio do not define executable identity. Package version is independent of explicit plan `schema_version`.

## Persistence compatibility boundary

Current plans persist as deterministic `.utterplan.toml` files with schema v6; `FlowPlan.load()` accepts TOML only. The v6 TOML codec validates and constructs `FlowPlan`, and reads frozen v5 TOML through the sequential v5-to-v6 migration. Schemas v5 and v6 have no JSON Schema resources or current JSON plan format. Frozen JSON Schema definitions for historical schemas v1–v4 remain under versioned resources.

```text
current plan:
.utterplan.toml -- TOML decode / schema-v6 validation (or sequential v5 migration) --> FlowPlan --> consumer

legacy saved plan:
.utterplan.json -- explicit `utterplan migrate` --> current .utterplan.toml
```

Migration is not planning. Supported historical plans migrate through the registered sequential chain v1 -> v2 -> v3 -> v4 -> v5 -> v6. Every step operates on serialized plain data and does not rerun source parsing, preparation, NLP, planning, G2P, rendering, or audio processing. The v4-to-v5 projection verifies token spans and pause evidence and fails rather than guessing; v5-to-v6 preserves executable semantics and never invents unavailable source text. Downgrades are not supported.

`compile-many` orchestrates independent source documents in order. Each successful FlowPlan is validated and atomically saved before the next source is processed; ordinary failures are reported and later inputs continue unless fail-fast is requested. Its TOML report is operational data, not a FlowPlan.
