# Architecture

UtterPlan is an engine-independent compiler from one SSMD document (or explicitly selected plain-text document) to an executable speech plan. Consumers compile documents independently; UtterPlan does not load books or manage workspaces.

```text
one SSMD document / explicit plain text
                 |
                 v
       parse -> language semantics -> spokenform preparation
                 -> segmentation -> directive resolution
                 -> semantic pause intent -> internal compiler plan
                 |                                |
                 |                                +--> optional trace sidecar
                 v
       FlowPlan (ordered units, local segments)
              /                 \
       consumer A             consumer B
                 |
                 v
          G2P / renderer / audio
```

The dependency direction is from SSMD, spokenform, and phrasplit into UtterPlan, then from UtterPlan to consumer packages. UtterPlan must not depend on ttsready, Readio, engine registries, G2P packages, model runtimes, or audio packages. Book iteration belongs to consumers and conversion tools.

## Compiler and public plan boundary

`compile_document` returns a `CompileResult` containing the current immutable `FlowPlan`, renderer-independent diagnostics, and an optional `PreparationTrace`. `UtterancePlanner.plan` also returns `FlowPlan`. Compiler-only normalized graph state remains private. When requested, the trace retains source text/hash, coordinate maps, preparation provenance, diagnostics, and renderability evidence in a separate versioned TOML sidecar. Trace state is not renderer input and does not affect plan identity or TOML.

`FlowPlan` is the current v5 executable contract: ordered `FlowUnit` objects each own ordered `FlowSegment` records. Segments include prepared text, effective language, local tokens, semantic pause intents, directives, markers, and optional heading metadata. `DocumentInfo` retains compact portable document information; `LinguisticProvenance` identifies providers without retaining their documents. UtterPlan ends before G2P. Engine/model selection, synthesis, and audio composition happen downstream.

## Compiler-owned segmentation topology

Segmentation has four distinct layers: parser-owned paragraph events define paragraph regions; PhraseSplit supplies advisory sentence-boundary proposals; UtterPlan validates those proposals and owns canonical paragraph, sentence, and private sentence-part spans in prepared spoken-text coordinates; renderer-required language, directive, pause, marker, and media cuts subdivide a part into final segments. Positive-width atomic media spans protect their interiors from automatic sentence/part boundaries; zero-width media events remain renderer operations, not parts. The public v5 `FlowPlan` contains only the resulting compact ordered flow—there is no serialized sentence-parts table.

PhraseSplit failure or an invalid proposal batch falls back to deterministic, conservative terminal scanning. Unsafe automatic cuts inside provider-aware lexical content are merged or dropped before projection; the final flow-projection token-edge check remains defense in depth. Exact surface and non-whitespace coverage checks run before and after applicable repairs. This normalization is independent of `renderability_mode`: strict and repair compilation use the same topology, while renderability mode governs only the existing punctuation-repair policy. See the [coordinate-space contract](coordinate-spaces) for offset ownership.

## SSMD and preparation

The document parser calls SSMD with `dialect="0.9"` for every SSMD source path, including unversioned fragments selected with `document_format="ssmd"`. UtterPlan does not parse SSMD 0.8 or migrate source. Older documents must first be converted with `ssmd migrate FILE --to 0.9`. The `utterplan migrate` command imports serialized legacy plans and applies schema migrations only.

SSMD header language is authoritative over a fallback. The CLI can omit `--language` when the header declares a language; plain input always needs a fallback. A fallback never forces or rewrites document semantics.

Preparation creates structural and spoken representations internally. The executable FlowPlan retains only prepared segment text; it does not retain the exact source string, structural text, dense source-to-spoken maps, parser annotations, or global compiler token tables. These diagnostics/provenance survive only when an optional trace is requested. See the [coordinate-space contract](coordinate-spaces).

## Pause and directive semantics

Authored SSMD breaks and semantic pause strengths project to local `PauseIntent` values on segment edges. The plan does not invent numeric durations or serialize an activation policy. Application pause mode controls which intents the compiler activates; consumer-specific timing policy remains downstream. Exact authored timed breaks remain exact. Ambiguous historical pause evidence fails migration rather than being guessed.

Typed directives are renderer-neutral values resolved from SSMD scopes and voice defaults. Logical voice bindings remain references, not concrete engine voices. Audio references and extension names are data only; UtterPlan does not fetch media or execute handlers.

## Identity and determinism

Plan identity is deterministic and renderer-independent. The v5 `plan_id` hashes executable flow and compact portable metadata rather than source text or TOML formatting. Flow-unit hashes use `utterplan-flow-v1` over local ordered segment semantics. Trace data, provider documents, model sessions, diagnostics, producer/package version, G2P output, and audio do not define executable identity. Package version is independent of explicit plan `schema_version`.

## Persistence compatibility boundary

Current plans persist as deterministic `.utterplan.toml` files with schema v5; `FlowPlan.load()` accepts TOML only. The v5 TOML codec validates and constructs `FlowPlan`. Schema v5 deliberately has no JSON Schema resource or current JSON plan format. Frozen JSON Schema definitions for historical schemas v1–v4 remain under versioned resources.

```text
current plan:
.utterplan.toml -- TOML decode / schema-v5 validation --> FlowPlan --> consumer

legacy saved plan:
.utterplan.json -- explicit `utterplan migrate` --> current .utterplan.toml
```

Migration is not planning. Supported historical plans migrate through the registered sequential chain v1 -> v2 -> v3 -> v4 -> v5. Every step operates on serialized plain data and does not rerun source parsing, preparation, NLP, planning, G2P, rendering, or audio processing. The v4-to-v5 projection verifies token spans and pause evidence and fails rather than guessing. Downgrades are not supported.

`compile-many` orchestrates independent source documents in order. Each successful FlowPlan is validated and atomically saved before the next source is processed; ordinary failures are reported and later inputs continue unless fail-fast is requested. Its TOML report is operational data, not a FlowPlan.
