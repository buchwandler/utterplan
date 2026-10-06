# Architecture

UtterPlan is the canonical renderer-independent compiler from one SSMD document
(or explicitly selected plain-text document) to an executable semantic speech
plan. Consumers compile each chapter/document separately; UtterPlan does not load
books or manage `.ssmdbook` or Readio workspaces.

```text
one SSMD document / explicit plain text
                 |
                 v
        parse -> language semantics -> spokenform preparation
                 -> segmentation -> directive/default resolution
                 -> pause resolution -> units and semantic identity
                 |
                 v
            UtterancePlan
              /       \
     ttsready report   Readio lowering
                         |
                         v
                G2P / renderer / audio
```

The dependency direction is `ssmd`, `spokenform`, and `phrasplit` into UtterPlan,
then from UtterPlan to consumer packages. UtterPlan must not depend on ttsready,
Readio, ssmdconvert, engine registries, G2P packages, model runtimes, or audio
packages. Book iteration belongs to consumers and conversion tools.

The public `compile_document` entry point returns a `CompileResult` containing a
portable `UtterancePlan`, renderer-independent diagnostics, and an optional
`PreparationTrace`. The trace explains preparation for reports/debugging only; it
is not renderer input, is not stored in the plan, and does not affect plan identity.
Legacy `UtterancePlanner.plan` remains a compatibility API returning only the
plan.

The public `UtterancePlan` Python object is immutable in-process renderer input;
the `.utterplan.toml` document is the portable persistence and semantic interchange
format; it encodes semantic schema v4. UtterPlan ends before G2P. Engine/model
selection, synthesis, and audio composition happen downstream.

## SSMD source contract

The document parser calls SSMD with `dialect="0.9"` for every SSMD source path,
including unversioned fragments selected with `document_format="ssmd"`. UtterPlan
does not parse SSMD 0.8 or migrate source. Older documents must first be converted
with `ssmd migrate FILE --to 0.9`. The `utterplan migrate` command explicitly
imports legacy JSON plans and applies serialized schema migrations.

SSMD header language is authoritative over a fallback language. The CLI can omit
`--language` when the header declares a language; plain input always needs an
explicit fallback. A fallback never forces or rewrites document semantics.

Declared annotations remain distinct from effective segment directives.
`plan.annotations` preserves authored spans, `document_metadata` preserves
portable header semantics, and `segment.directives` contains resolved
renderer-neutral values after scope and voice-default resolution. Audio references
and extension names are preserved as data only. UtterPlan does not retrieve media
or execute handlers.

Preparation preserves structural and spoken coordinate spaces. `spoken_start`,
`spoken_end`, and `spoken_position` refer to prepared text. Renderers must use
these ranges when consuming `PlanSegment.text`, `AnnotationSpan`, and
`TokenAnnotation`; structural/source offsets are not valid slices into prepared
text. Preparation-trace source offsets address SSMD-clean structural text, while
its transformation output offsets address prepared spoken text.

Linguistic analysis and provider documents are request-local. Returned plans
contain plain, round-trippable semantic data only: no live parser objects, spaCy
documents, models, sessions, provider caches, phonemes, engine token IDs, or audio.
A reusable planner may share sequential resource caches, but concurrent use is not
promised.

The persisted `linguistic_runs` collection describes final pass-B token ranges.
Pass-A documents and tokens remain request-local because written-to-spoken
preparation can invalidate their offsets.

Pause events retain provenance and resolved event IDs. Pause defaults are
normalized to finite seconds with explicit precedence, and segments expose
resolved pauses directly. Semantic boundaries are a separate immutable
collection of stable spoken-text split opportunities; they have no duration,
activation state, or renderer choice. Logical voices are intent references;
document `voice_bindings` metadata remains separate and no concrete engine
voice is selected.

Plan identity is deterministic and renderer-independent. It covers semantic source/configuration/metadata; it does not include renderer-only model, sample
rate, or output-file settings. Unit hashes include ordered segment semantics,
resolved pauses, marker content, and semantic token facts referenced by each
segment. Semantic-boundary positions relative to each unit are part of the
`utterplan-unit-v3` hash; diagnostics and producer metadata do not define unit
identity. Package version is derived by setuptools-scm and is independent of
the explicit UtterPlan `schema_version`.

Current plans persist as deterministic `.utterplan.toml` files; schema v4 remains the semantic contract, and `plan_id` is derived from canonical semantic data rather than TOML bytes. `UtterancePlan.load()` accepts TOML only. Legacy JSON plan import is an explicit migration command, never a normal load fallback.

`compile-many` orchestrates independent source documents in order. Each successful plan is validated and atomically saved before the next source is processed; ordinary failures are reported and later inputs continue unless fail-fast is requested. Its atomically refreshed TOML report is operational data, not an `UtterancePlan`.

## Persistence compatibility boundary

```text
current plan file:
.utterplan.toml -- TOML decode / schema-v4 validation --> UtterancePlan --> renderer

legacy saved plan:
.utterplan.json -- explicit `utterplan migrate` --> current .utterplan.toml
```

Migration is not planning. UtterPlan owns persistence, schema validation, and migration. Renderers consume only the current in-memory `UtterancePlan` and do not implement historical schema branches.

Schema v4 is current. Released schemas v1, v2, and v3 remain frozen; supported plans migrate through the registered sequential chain to v4. The v3-to-v4 step transforms serialized data only and does not rerun parsing, NLP, planning, G2P, rendering, or audio processing. Consumers receive only the current in-memory model.
