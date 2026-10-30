---
title: "Architecture Documentation"
version: 6
generator: "archledger 0.4.0"
arc42_template_version: "9.0-EN"
---

# Architecture Documentation

Generated from archledger records. Do not edit this generated file directly.

# Introduction and Goals

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
Downstream FlowPlan consumers
       |
       v
G2P / synthesis / audio (downstream)
```

The compiler produces one FlowPlan per source item. The `bundle` CLI and public
services accept a canonical `.ssmd-bundle/` root and dispatch book or document
behavior from the `manifest.json` format. Compilation and profile-specific
RenderPlan projection leave source content and manifests unchanged.

## Manifest-driven bundles

An `ssmdconvert.book` v1 manifest maps chapters to independently compiled items;
an `ssmdconvert.document` v1 manifest maps one document to one FlowPlan. Both use
the same root shape and unified `bundle compile`, `bundle render`, and `bundle replan` lifecycle. The manifest format, not the directory contents, determines
the kind.

## Requirements Overview

<!-- archledger: no accepted records for this section yet -->

## Quality Goals

<!-- archledger: no accepted records for this section yet -->

## Stakeholders

<!-- archledger: no accepted records for this section yet -->

# Architecture Constraints

The following constraints are binding development rules for UtterPlan and are
enforced by tests where possible.

- **Engine independence.** Core code must not import PyKokoro, PiperSynth,
  kokorog2p, piperg2p, ONNX Runtime, audio packages, or any consumer package.
- **UtterPlan ends before G2P.** Engine/model selection, synthesis, and audio
  composition happen downstream.
- **Public plan purity.** Public FlowPlan objects contain no phonemes, model token
  IDs, models, sessions, or audio. Completed plans must not retain spaCy or
  provider documents.
- **Schema contract.** `.utterplan.toml` schema v7 is the current inter-package
  contract. Schema-v5/v6 TOML and historical JSON schemas v1–v4 remain sequential
  migration inputs only.
- **Roundtrip survivability.** Python objects may not contain semantic state that
  cannot survive file roundtrip.
- **Coordinate discipline.** Every offset has a documented coordinate space (see
  the [coordinate-space contract](coordinate-spaces)).
- **Deterministic defaults.** Default planning is deterministic.
- **Schema governance.** Schema changes require explicit compatibility review,
  frozen historical fixture coverage, deterministic migration tests, and package
  artifact checks. Released schema files are immutable and retained under versioned
  paths; schemas v5, v6, and v7 have no JSON Schema resources.
- **Data-only migrations.** Migrations operate on serialized plain data and may not
  call parser, planner, G2P, renderer, or audio stages.
- **Version independence.** Package version and schema version remain independent.
  Migration preserves a compiled plan; replanning is a separate operation.
- **Trace isolation.** Optional compiler traces are sidecars; they must never alter
  executable plan content or identity.
- **Self-contained tests.** Repository tests must not require sibling consumer
  checkouts; consumer-specific compatibility testing belongs in the consumer
  repository.

<!-- archledger: no accepted records for this section yet -->

# Context and Scope

## External context

Dependency layering (each component uses the dependency above it):

```text
Spokenform
    ^
TTSReady
    ^
UtterPlan
    ^
Downstream FlowPlan consumers
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
  projection; downstream renderers consume portable RenderProfiles and RenderPlans,
  while other downstream consumers consume FlowPlans. Engine selection, preflight,
  and speech execution are outside UtterPlan.

## In scope

- One document (SSMD 0.9, or explicitly selected plain text) to one executable,
  deterministic FlowPlan v7.
- Written-to-spoken preparation via TTSReady (plain text) or the SSMD-authoritative
  preparer (SSMD).
- Canonical segmentation, safe-boundary inventory, authored pause intents, typed
  directives, and markers.
- Optional provenance trace sidecars and renderer-neutral diagnostics.
- Manifest-driven book/document bundle dispatch through the unified `bundle` commands,
  using only canonical `.ssmd-bundle/` roots and leaving source content unchanged.
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

## Manifest-driven bundle inputs

- Bundle commands accept only a canonical `<name>.ssmd-bundle/` root with a
  `manifest.json`; the format field selects book or document behavior.
- Book manifests map source-numbered chapters to independent FlowPlans and support
  manifest-ordered selection.
- Document manifests map one SSMD 0.9 source to one FlowPlan and accept only the
  `all` selector.
- Both kinds use the shared `bundle compile`, `bundle render`, and `bundle replan` lifecycle. Manifest digests remain provenance; current source content is
  compiled without modifying the manifest or source files.

## Business Context

<!-- archledger: no accepted records for this section yet -->

## Technical Context

<!-- archledger: no accepted records for this section yet -->

# Solution Strategy

UtterPlan follows a strict stage pipeline in which every stage produces plain,
serializable data:

1. **Parse.** The document parser calls SSMD with `dialect="0.9"` for every SSMD
   source path, including unversioned fragments selected with
   `document_format="ssmd"`. Plain-text input is explicit and always requires a
   language fallback; SSMD header language is authoritative over a fallback and a
   fallback never rewrites document semantics.
2. **Analyze source.** Provider-neutral token hints, protected spans, and an
   explicit linguistic profile are produced; spaCy enrichment is best effort with a
   deterministic fallback.
3. **Prepare.** Preparation `auto` resolves after the input format is known: plain
   text uses TTSReady/Spokenform, while SSMD uses the SSMD-authoritative preparer to
   apply reviewed `sub` aliases exactly once. SSMD compilation in this mode does not
   call Spokenform; explicit `spokenform` remains an opt-in legacy path and emits a
   warning.
4. **Map and re-analyze.** UtterPlan maps prepared spoken text back onto source
   coordinates and runs spoken-text analysis.
5. **Segment and bound.** Paragraph events, validated sentence proposals
   (PhraseSplit), language/directive/pause/marker/media cuts, and atomic media-span
   protection produce the canonical span and boundary inventory.
6. **Project.** Flow projection assembles paragraph-local `FlowUnit` objects with
   ordered `FlowSegment` records, segment-local tokens, replacement views, boundary
   arrays, and pause intents, guarded by a token-edge coverage check as defense in
   depth.

Supporting tactics:

- **Engine independence by construction.** The dependency direction is
  `PyKokoro or another renderer -> UtterPlan`; import-boundary tests keep engine,
  G2P, runtime, audio, and consumer packages out of core code.
- **Determinism by default.** Fixed orderings, no wall-clock or environment inputs
  in defaults, and identity hashing that never hashes TOML formatting.
- **Safety separation.** Canonical safe-boundary opportunities and authored pause
  intents are distinct facts that may coexist at one edge; renderers realize them
  independently.
- **Data-only evolution.** Registered migration steps walk serialized plain data
  through v1 -> v2 -> v3 -> v4 -> v5 -> v6 and intentionally refuse the v6-to-v7
  step (`migration.recompile_required`) because legacy data cannot prove a complete
  boundary inventory.
- **Sidecar provenance.** Detailed diagnostics, coordinate maps, and renderability
  evidence live in an optional versioned trace TOML that never affects plan
  identity or executable content.

## Prepared character-spelling semantics

After written-to-spoken preparation and before segmentation, UtterPlan inspects verified replacement records for the exact character-spelling transformation: an ASCII uppercase-letter/digit core of at least two characters becomes the same characters joined by single spaces, optionally retaining an identical `'s` or `’s` suffix. This derives a compiler-owned `say_as=characters` annotation over only the prepared character core. For example, `[ART]{sub=\"A R T\"}` keeps prepared text `A R T`; `[ART's]{sub=\"A R T's\"}` keeps `A R T's` and marks only `A R T`.

The derivation is portable executable intent, not a renderer-specific spelling rewrite. Prepared text never becomes `A- R- T`; a renderer adapter may choose that frontend form. Existing semantic-edge segmentation produces the exact controlled span, while default RenderPlan sentence grouping retains the full sentence as one normal speech request with a request-local control. An explicit manual `pauses.parenthetical` duration is a separate opt-in policy: RenderPlan may split at UtterPlan's stored parenthetical edges and project pauses without reparsing or rewriting text; profiles without it keep the existing grouping.

Authored `say-as` semantics take precedence, and the consumed SSMD `sub` annotation remains consumed. The derived directive uses existing schema-v7 `SayAsDirective` serialization and identity hashing; replacement records remain diagnostic provenance and are not synthesis input. No schema version or migration changes are required.

## Strategy Items

<!-- archledger: no accepted records for this section yet -->

# Building Block View

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

Preparation semantics include the compiler-only `prepared_semantics.py` pass. It consumes verified preparation replacement records after text preparation and before language-run/segment construction, appending deterministic `say-as=characters` annotations without changing prepared text, replacement provenance, boundaries, source maps, or consumed substitutions. It reuses existing directive resolution, semantic-edge segmentation, FlowPlan v7 serialization/identity, and RenderPlan request-local control projection.

<!-- archledger: no accepted records for this section yet -->

# Runtime View

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

<!-- archledger: no accepted records for this section yet -->

# Deployment View

UtterPlan deploys as a single pure-Python package with no engine, model runtime,
or audio dependencies:

- **Distribution.** Published on PyPI as `utterplan`; the package version is
  dynamically derived from Git tags by setuptools-scm and is independent of the
  plan schema version.
- **Installation shapes.** Installed as a library (`pip install utterplan`) for
  downstream FlowPlan consumers, or with the `utterplan` CLI for canonical
  manifest-driven `.ssmd-bundle/` workflows. Development installs use
  `pip install -e '.[dev,docs]'`.
- **Optional linguistic enrichment.** spaCy models are preferred in `sm`, `md`,
  `lg`, `trf` order when already installed; UtterPlan never downloads models and
  continues with deterministic fallback tokens when spaCy or every compatible local
  model is unavailable. Explicit tiers can be required via configuration.
- **No runtime services.** Everything runs in-process; there is no server, daemon,
  network fetch, or audio device access. Media references and extension names in
  plans are data only.
- **Downstream placement.** Consumers of UtterPlan's portable FlowPlan and optional
  RenderPlan contracts add engines, model runtimes, G2P, synthesis, and audio on their
  side of the boundary; UtterPlan does not import those packages.
- **Documentation.** Sphinx docs build from `docs/` with
  `sphinx-build -W --keep-going -b html docs docs/_build/html`.
- **Quality gate.** `python -m pytest -q`, `ruff check .`, and `mypy utterplan` run
  against the self-contained repository test suite.

- **Manifest-driven bundle lifecycle.** Schema-v1 book and document manifests use
  the same canonical `.ssmd-bundle/` root and unified `bundle` compile, render,
  and replan services. Source content and manifests remain read-only.

<!-- archledger: no accepted records for this section yet -->

# Cross-cutting Concepts

## Coordinate spaces

Every offset has a documented coordinate space (see the
[coordinate-space contract](coordinate-spaces)). Token `start`/`end` offsets are
Python-character indexes into the owning segment's `text`, never document-global
coordinates. Replacement spans are local to the final prepared segment text; full
source maps remain in the optional trace.

## Compiler-owned segmentation topology

Segmentation has four distinct layers: parser-owned paragraph events define
paragraph regions; PhraseSplit supplies advisory sentence-boundary proposals;
UtterPlan validates those proposals and owns canonical paragraph, sentence, and
private sentence-part spans in prepared spoken-text coordinates; language,
directive, authored-pause, marker, and media cuts subdivide a part into final
segments. Positive-width atomic media spans protect their interiors from automatic
sentence/part boundaries; zero-width media events remain renderer operations, not
parts. The public v7 FlowPlan contains only the resulting compact ordered
flow—there is no serialized sentence-parts table.

PhraseSplit failure or an invalid proposal batch falls back to deterministic,
conservative terminal scanning. Unsafe automatic cuts inside provider-aware lexical
content are merged or dropped before projection; the final flow-projection
token-edge check remains defense in depth. Exact surface and non-whitespace
coverage checks run before and after applicable repairs. This normalization is
independent of `renderability_mode`: strict and repair compilation use the same
topology, while renderability mode governs only the punctuation-repair policy.

## Pause and directive semantics

Authored SSMD breaks project to local `PauseIntent` values on segment edges, while
safe clause, sentence, paragraph, parenthetical, and voice-change opportunities are
carried separately as boundary kinds. Both facts may coexist at one edge. UtterPlan
does not activate automatic pauses or invent numeric durations; downstream
renderers choose native, automatic, or manual realization. Exact authored timed
breaks remain exact. Ambiguous historical pause evidence fails migration rather
than being guessed.

Typed directives are renderer-neutral values resolved from SSMD scopes and voice
defaults. Logical voice bindings remain references, not concrete engine voices.
Audio references and extension names are data only; UtterPlan does not fetch media
or execute handlers.

## Identity and determinism

Plan identity is deterministic and renderer-independent. The v7 `plan_id` includes
the exact UTF-8 SHA-256 digest of optional raw source, plus executable flow,
canonical boundary opportunities, authored pause intents, and compact portable
metadata; it never hashes TOML formatting. The v7 `utterplan-flow-v3` identity
includes boundaries, while v5/v6 retain their historical hash schemas. Renderer
chunk and pause strategies are not identity inputs. Trace data, provider documents,
model sessions, diagnostics, producer/package version, G2P output, and audio do not
define executable identity. Package version is independent of explicit plan
`schema_version`.

## Preparation and source retention

Preparation creates structural and spoken representations internally. The
executable FlowPlan retains prepared segment text and compact segment-local
replacement views, and v7 stores the exact raw input once in its optional
`PlanSource` record; it does not retain structural text or full source-to-spoken
maps, parser annotations, or global compiler token tables. Detailed diagnostics and
complete provenance mappings remain in an optional trace.

## Persistence and atomic IO

Plans persist as deterministic `.utterplan.toml` files. Writes use atomic IO
(temporary file plus replace) so interrupted operations never leave partial plan
files; the same mechanism protects batch reports and book outputs.

## Renderability policy

Safe punctuation-only repair is the default; `--renderability strict` rejects every
repair opportunity. Neither mode guesses a symbol's pronunciation or crosses
semantic blockers. Blocked planning outcomes may be reviewed through the separate
`utterplan.planning-attempt.v1` inspect-only artifact; such candidates remain
drafts and never become canonical plans.

### Character spelling: text, intent, and realization

Character spelling keeps four concerns separate: source spelling (for example, `ART`), prepared spoken text (`A R T`), portable executable intent (`say_as=characters` over the exact prepared core), and downstream renderer realization. The matcher uses only verified replacement metadata and does not guess from arbitrary uppercase words or normalization changes. Possessive suffixes remain outside the semantic range. Replacement provenance is excluded from executable identity; the derived directive affects FlowUnit and FlowPlan identity. UtterPlan never persists a frontend-specific hyphen form or adds a pause for this feature.

<!-- archledger: no accepted records for this section yet -->

# Architecture Decisions

- **AD: SSMD 0.9 only.** The document parser calls SSMD with `dialect="0.9"` for
  every SSMD source, including unversioned fragments selected with
  `document_format="ssmd"`. UtterPlan does not parse 0.8 or migrate source; source
  conversion belongs to `ssmd migrate`. _Rationale:_ one canonical input dialect;
  `utterplan migrate` stays a serialized-plan operation.
- **AD: Format-dependent preparation.** Preparation `auto` resolves after the input
  format is known — plain text goes through TTSReady/Spokenform, SSMD goes through
  the SSMD-authoritative preparer applying reviewed `sub` aliases exactly once.
  _Rationale:_ SSMD annotations must be applied exactly once and authoritatively;
  plain text reuses the shared written-to-spoken machinery.
- **AD: Boundaries are separate from authored pauses.** Safe clause, sentence,
  paragraph, parenthetical, and voice-change opportunities are carried as boundary
  kinds independently of authored `PauseIntent` values; both may coexist at one
  edge. UtterPlan neither activates automatic pauses nor invents durations.
  _Rationale:_ renderers keep native, automatic, or manual realization freedom
  without recompilation.
- **AD: Boundaries participate in v7 identity.** The v7 `utterplan-flow-v3`
  `plan_id` includes the boundary inventory; v5/v6 keep their historical hash
  schemas. _Rationale:_ boundaries are executable facts, so identity must cover
  them.
- **AD: v6-to-v7 migration refuses.** The step returns
  `migration.recompile_required`. _Rationale:_ serialized v6 semantics cannot prove
  a complete boundary inventory; guessing would corrupt the safety contract.
- **AD: TOML-only persistence.** Current plans persist as deterministic
  `.utterplan.toml`; `FlowPlan.load()` accepts TOML only and rejects JSON.
  Historical JSON Schema resources for v1–v4 stay frozen and immutable.
  _Rationale:_ one portable interchange format; strict load rejects ambiguity.
- **AD: Traces are sidecars.** Optional compiler traces carry source text/hash,
  coordinate maps, preparation provenance, diagnostics, and renderability evidence
  in a separate versioned TOML. _Rationale:_ provenance must never alter executable
  content or identity.
- **AD: One canonical, manifest-dispatched bundle lifecycle.** All bundle commands
  accept only `<name>.ssmd-bundle/` roots and choose book or document behavior from
  schema-v1 `manifest.json`. Books produce independent plans per selected source
  number; a document bundle produces one plan. Compilation, projection, and replan
  never modify source files or manifests. _Rationale:_ preserve item-level semantics
  and source ownership while giving downstream packages one stable contract.

- **AD: Best-effort spaCy with deterministic fallback.** Models are preferred in
  `sm`/`md`/`lg`/`trf` order when already installed and never downloaded; without
  spaCy, planning continues with deterministic fallback tokens. _Rationale:_
  reproducibility and offline safety outweigh always-on enrichment.
- **AD: Package and schema versions are independent.** Migration preserves a
  compiled plan; replanning is a separate operation. _Rationale:_ schema evolution
  must not force package-version coupling or silent replans.

<!-- archledger: no accepted records for this section yet -->

# Quality Requirements

- **Determinism.** Default planning is deterministic. Identical source and
  configuration always produce identical executable content and `plan_id`; identity
  hashing never hashes TOML formatting and excludes renderer chunk/pause strategies,
  trace data, provider documents, diagnostics, producer version, G2P output, and
  audio.
- **Portability / roundtrip survivability.** Python objects may not contain
  semantic state that cannot survive file roundtrip. Plans reload from
  `.utterplan.toml` byte-stable; saved and loaded plans compare equal.
- **Engine independence.** Core code must not import PyKokoro, PiperSynth,
  kokorog2p, piperg2p, ONNX Runtime, audio packages, or consumer packages; the
  intended dependency direction is `renderer -> UtterPlan`, enforced by
  import-boundary and dependency-architecture tests.
- **Plan purity.** Public FlowPlan objects contain no phonemes, model token IDs,
  models, sessions, or audio; completed plans retain no spaCy or provider
  documents.
- **Robustness.** PhraseSplit failure or invalid proposal batches fall back to
  deterministic conservative terminal scanning; unsafe cuts are merged or dropped;
  exact surface and non-whitespace coverage checks run before and after repairs;
  the final token-edge check is defense in depth. Interrupted writes never leave
  partial files (atomic IO).
- **Compatibility governance.** Schema changes require explicit compatibility
  review, frozen historical fixture coverage, deterministic migration tests, and
  package artifact checks. Every supported older schema retains a sequential
  data-only migration path to current; ambiguous historical pause evidence fails
  migration rather than being guessed.
- **Testability.** The repository test suite is self-contained (golden fixtures,
  migration fixtures, schema-history fixtures, consumer-contract tests) and must
  not require sibling consumer checkouts; consumer-specific compatibility testing
  belongs in the consumer repository.
- **Operational transparency.** Renderer-neutral diagnostics always report
  failures; terminal diagnostics default to warnings with `all`/`none` overrides;
  batch and book reports retain every diagnostic; typed progress callbacks expose
  long-running planning without changing the plan.

## Quality Requirements Overview

<!-- archledger: no accepted records for this section yet -->

## Quality Scenarios

<!-- archledger: no accepted records for this section yet -->

# Risks and Technical Debt

- **Historical schema surface.** Four frozen JSON Schema readers (v1–v4) plus
  schema-v5/v6 TOML migration inputs must keep working and stay immutable under
  versioned paths. Each schema change adds compatibility-review and fixture burden.
- **v6 plans cannot be promoted.** The v6-to-v7 step intentionally refuses with
  `migration.recompile_required`; owners of v6 archives must recompile from source.
- **Ambiguous legacy pause evidence fails migration.** Correct but strict: archives
  with ambiguous historical pause evidence need manual review instead of a guess.
- **spaCy environment divergence.** Best-effort enrichment means plans compiled
  with different locally installed model tiers (`sm`/`md`/`lg`/`trf`) can carry
  different token facts; the deterministic fallback is the reproducibility anchor.
  Consumers must not retokenize or rerun spaCy on v7 token views.
- **Advisory proposal dependence.** Sentence-boundary quality depends on
  PhraseSplit proposals; the conservative fallback protects correctness but may
  produce fewer, larger parts when proposals fail.
- **Renderer-side interpretation debt.** Media references, extension names, and
  logical voice bindings are data only; correctness of fetch, handler execution,
  and voice resolution rests entirely with consumers.
- **Book workflows stay per-file.** No book-level plan exists by design; any future
  cross-chapter concerns (ordering guarantees, global numbering) must remain
  orchestration-level and must not leak into chapter plans.

## Risk Overview

<!-- archledger: no accepted records for this section yet -->

# Glossary

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
| SSMD bundle      | Canonical `.ssmd-bundle/` root whose schema-v1 manifest selects book items or a single document item; all operations use the unified `bundle` lifecycle.                                            |
| Planning attempt | Inspect-only `utterplan.planning-attempt.v1` artifact for reviewing blocked renderability outcomes; never a canonical plan.                                                                         |
| plan_id          | Deterministic renderer-independent plan identity; v7 `utterplan-flow-v3` includes boundaries and never hashes TOML formatting.                                                                      |

<!-- archledger: no accepted records for this section yet -->
