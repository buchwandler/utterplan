# Python API

The canonical public entry point is `compile_document`, which compiles one SSMD
document or explicitly configured plain-text document and returns a `CompileResult`.
Its `plan` is the immutable, round-trippable renderer-facing `FlowPlan`; its
diagnostics describe compilation, and an optional `PreparationTrace` holds compiler
provenance separately. `UtterancePlanner.plan` is also supported and returns the
same current `FlowPlan` directly.

The Python defaults are deliberately spaCy-free and repair-first: `PlannerConfig` uses `spokenform` text preparation and `renderability_mode="repair"`, while `PauseConfig().mode` is `"tts"`. The CLI additionally defaults to the `spacy off` linguistic-resource policy, which uses deterministic fallback tokenization and analysis without requiring an installed spaCy model.

For an explicit contextual-G2P configuration, use `LinguisticsConfig(use_spacy=True, spacy_model="en_core_web_sm", require_spacy=True)`. The resulting plan records final pass-B token provenance in `linguistic_runs`; no provider document is retained.
spaCy enrichment is opt-in through the CLI's `--spacy auto` policy or an explicit `LinguisticsConfig` with a compatible local model. It may provide richer tokenization, POS tags, lemmas, and tags, but UtterPlan never downloads a model implicitly.

## Canonical single-document compiler

`compile_document` is the shared semantic interpretation boundary for independent
consumers. It does not load books, traverse chapters, or manage consumer workspaces.
SSMD header language takes precedence over a fallback; the explicit
`fallback_language` keyword is a per-call fallback override, never a forced language.
`PlannerConfig.language` remains required for compatibility and supplies the fallback
when `fallback_language` is omitted. Plain input must have a language fallback.

```python
from utterplan import PlannerConfig, compile_document

result = compile_document(
    ssmd_source,
    input_format="ssmd",
    config=PlannerConfig(language="en-us"),
    trace=True,
)
plan = result.plan
assert result.plan is plan
assert result.trace is not None
```

Use `input_format="plain"` only for explicitly configured plain text. A trace
contains explanatory per-unit preparation information but is not serialized into
the plan, is not renderer input, and does not change `plan.plan_id`. Its source
ranges index SSMD-clean structural text; transformation output ranges index prepared
spoken text, using Python string character offsets.

## Persistable planning attempts

`compile_attempt` and `UtterancePlanner.compile_attempt` expose a finalized planning
outcome without raising solely because a segment is not renderable. They still raise
for input, configuration, and planning failures. The existing `compile_document`,
`UtterancePlanner.compile`, and `plan` APIs remain strict and continue raising
`PlanRenderabilityError` when renderability blocks completion.

Attempts are separate from canonical plans. A blocked attempt retains an inspect-only
candidate draft; it is not a valid `FlowPlan` and cannot be loaded by
`FlowPlan.load()`. Persist it with `PlanningAttempt.save()` and restore it with
`PlanningAttempt.load()`; the attempt TOML schema is
`utterplan.planning-attempt.v1`, independent of canonical plan schema v5.

```python
from utterplan import PlannerConfig, compile_attempt

attempt = compile_attempt(
    "Hello.\n\n.\n\nWorld.",
    input_format="plain",
    config=PlannerConfig(
        language="en-us",
        renderability_mode="strict",
    ),
)
assert attempt.status == "blocked"
attempt.save("chapter.attempt.toml")

for issue in attempt.renderability.issues:
    assessment = issue.repair_assessment
    if assessment is not None:
        print(issue.segment_id, assessment.safe, assessment.action)
        print(assessment.blockers)
```

Repair assessments report the existing conservative options; they do not rewrite
text speculatively. In repair mode, only the planner's established safe repairs are
applied. `utterplan inspect-attempt chapter.attempt.toml --issues` shows issues,
source locations, and repair assessments; `--segment` and `--unit` select candidate
topology, and `--json` emits the complete attempt as JSON for inspection.

## TOML persistence

Schema v5 is the semantic contract, while `.utterplan.toml` is the canonical persisted format. `FlowPlan.to_toml()` and `FlowPlan.from_toml()` round-trip the executable plan; `save()` writes atomically, and `load()` accepts TOML only. Historical v4 TOML is migrated to v5 by the codec; historical JSON plans require the explicit migration command.

```python
from utterplan import FlowPlan

toml_text = plan.to_toml()
restored = FlowPlan.from_toml(toml_text)
assert restored == plan
plan.save("chapter.utterplan.toml")
assert FlowPlan.load("chapter.utterplan.toml") == plan
```

`FlowPlan.to_dict()` and `FlowPlan.from_dict()` expose the v5 executable mapping. For a legacy JSON file, use `utterplan migrate old.utterplan.json -o current.utterplan.toml`; SSMD source migration is a separate operation.

## Incremental batch compilation

The public batch API compiles independent requests one at a time, atomically commits each successful plan, and yields an outcome without retaining the plan object. Ordinary per-document read, planning, validation, serialization, and write failures become failed outcomes and processing continues by default. Set `fail_fast=True` to skip later requests after the first failure. Existing files are protected unless `force=True` is explicit. An optional TOML operational report is refreshed after each outcome.

```python
from pathlib import Path

from utterplan import CompileRequest, PlannerConfig, compile_to_files

requests = [
    CompileRequest(
        id="chapter-1",
        source=Path("chapters/one.ssmd"),
        output=Path("plans/one.utterplan.toml"),
        input_format="auto",
    ),
    CompileRequest(
        id="chapter-2",
        source=Path("chapters/two.ssmd"),
        output=Path("plans/two.utterplan.toml"),
        input_format="auto",
    ),
]
for outcome in compile_to_files(
    requests,
    config=PlannerConfig(language="en-us"),
    report_path="plans/compile-report.toml",
):
    print(outcome.status, outcome.source_label, outcome.output)
```

The report is operational data, not a semantic plan, and must not be passed to `FlowPlan.load()`. Unexpected programming and progress-callback errors propagate rather than being converted to document failures.

## Planner progress callbacks

`UtterancePlanner.plan`, `UtterancePlanner.compile`, and `compile_document` accept an optional keyword-only `on_progress` callback. It receives typed `PlannerProgressEvent` objects synchronously in the planner thread. Progress is operational only: it is not added to `PlannerConfig` or the plan, and enabling a callback does not change plan identity or serialization.

```python
from utterplan import PlannerConfig, PlannerProgressEvent, UtterancePlanner


def report(event: PlannerProgressEvent) -> None:
    if event.kind == "run.started":
        print(
            event.phase,
            event.pass_index,
            event.language,
            event.provider,
            event.model,
        )


planner = UtterancePlanner(PlannerConfig(language="en-us"))
plan = planner.plan(text, on_progress=report)
```

The phase events cover parsing, source analysis, preparation, spoken analysis, segmentation, and finalization. Each provider run reports `run.started` and `run.completed`; `completed` counts fully completed runs and `total` is the number of runs in that phase. When a local spaCy model is actually loaded, `model.started` and `model.completed` identify its language, provider, and resolved model. Cached models produce no load events. Events contain primitive metadata only, never spaCy pipelines or documents.

Callbacks should be lightweight. An exception raised by a callback propagates to the caller and can be used to stop planning. A provider invocation such as `pipeline(text)` is one opaque work unit: events report its start and completion but do not claim smooth percentages or internal progress. If spoken-text preparation leaves the linguistic input unchanged, the planner can reuse source analysis; the `spoken_analysis` phase events expose `details["reused"] = True` and no provider-run events are emitted for that reuse. Identity preparation also reports `source_analysis` as skipped (`details["skipped"] = True`) because it does not use source analyses; the single actual provider pass runs as logical pass 2.

## SSMD input and semantic plan

The SSMD parser accepts dialect 0.9 only. Select SSMD explicitly for unversioned canonical fragments with `PlannerConfig(document_format="ssmd")`. Older SSMD source must be migrated with `ssmd migrate FILE --to 0.9`; `migrate_plan_data` operates on serialized plan mappings, while `utterplan migrate` imports legacy plans, not source documents.

`PlannerConfig.document_format` defaults to `"plain"`, so SSMD syntax is never inferred for an ordinary Python string. Set it to `"ssmd"` for SSMD documents or fragments. Application `PauseConfig.mode` controls semantic pause activation; authored SSMD breaks and strengths are represented as pause intent, not assigned engine-specific durations.

```python
from utterplan import PlannerConfig, compile_document

ssmd_source = """---
ssmd_version: "0.9"
title: API example
language: en-us
---
Hello [world]{emphasis="strong"}.
"""
result = compile_document(
    ssmd_source,
    input_format="ssmd",
    config=PlannerConfig(language="en-us"),
    trace=True,
)
plan = result.plan
segment = plan.flow[0].segments[0]
assert plan.document.ssmd_version == "0.9"
assert result.trace is not None  # source spans/diagnostics are sidecar data
print(segment.directives.emphasis)
```

The `document` record retains compact portable document information. Effective directives and pause intents live on their owning flow segments. Compiler-only source spans and preparation coordinate maps remain in the optional trace. See the [coordinate-space contract](coordinate-spaces) and [consumer guide](consumer-guide) for renderer responsibilities.

## Flow segments and local tokens

A `FlowPlan` stores ordered `FlowUnit` objects. Each unit owns its ordered segments, so consumers do not join plan-global IDs. Token offsets use Python-character coordinates local to `segment.text`:

```python
for unit in plan.flow:
    for segment in unit.segments:
        for token in segment.tokens:
            surface = segment.text[token.start : token.end]
            print(segment.language, surface, token.lemma, token.pos)
```

Semantic pause intent is likewise local to the segment edge. It may be `none`, a semantic strength, or an exact authored timed pause; the consumer chooses any renderer-specific realization. Heading levels and marker names are already localized to the segments and units that own them.

## Audio/media segments

`AudioDirective` is already part of the public API. Inspect it on the segment; its
`src` is an opaque renderer input, and `segment.text` is optional spoken fallback:

```python
segment = plan.flow[0].segments[0]
audio = segment.directives.audio
if audio is not None:
    print(audio.src)  # Resolve externally; do not parse SFX URI syntax here.
    fallback_text = segment.text  # May be "" when no spoken fallback exists.
else:
    spoken_text = segment.text
```

Each SSMD audio annotation is represented by one audio-bearing segment. Separate
occurrences may have the same `src`; `segment.text` is not the media identity and
consumers do not need to inspect raw SSMD annotations to find media.

## Planner configuration

```{autoclass} utterplan.PlannerConfig
:members:
:show-inheritance:
```

```{autoclass} utterplan.PauseConfig
:members:
:show-inheritance:
```

```{autoclass} utterplan.LinguisticsConfig
:members:
:show-inheritance:
```

```{autoclass} utterplan.SSMDConfig
:members:
:show-inheritance:
```

## Planning and plan records

```{autofunction} utterplan.compile_document

```

```{autoclass} utterplan.CompileResult
:members:
```

```{autoclass} utterplan.PreparationTrace
:members:
```

```{autoclass} utterplan.PreparationTraceUnit
:members:
```

```{autoclass} utterplan.UtterancePlanner
:members:
:show-inheritance:
```

```{autoclass} utterplan.FlowPlan
:members:
:show-inheritance:
```

```{autoclass} utterplan.FlowUnit
:members:
:show-inheritance:
```

```{autoclass} utterplan.FlowSegment
:members:
:show-inheritance:
```

```{autoclass} utterplan.PauseIntent
:members:
:show-inheritance:
```

```{autoclass} utterplan.TokenView
:members:
:show-inheritance:
```

```{autoclass} utterplan.DocumentInfo
:members:
:show-inheritance:
```

```{autoclass} utterplan.LinguisticProvenance
:members:
:show-inheritance:
```

`UtterancePlan`, `PlanSegment`, and `PlanUnit` remain legacy compiler/migration models. Fresh compilation returns `FlowPlan`; renderers should use only the v5 flow contract.

## Renderer-neutral SSMD directives

```{autoclass} utterplan.SegmentDirectives
:members:
:show-inheritance:
```

```{autoclass} utterplan.VoiceDirective
:members:
:show-inheritance:
```

```{autoclass} utterplan.PronunciationDirective
:members:
:show-inheritance:
```

```{autoclass} utterplan.ProsodyDirective
:members:
:show-inheritance:
```

```{autoclass} utterplan.EmphasisDirective
:members:
:show-inheritance:
```

```{autoclass} utterplan.SayAsDirective
:members:
:show-inheritance:
```

```{autoclass} utterplan.SubstitutionDirective
:members:
:show-inheritance:
```

```{autoclass} utterplan.AudioDirective
:members:
:show-inheritance:
```

```{autoclass} utterplan.ExtensionDirective
:members:
:show-inheritance:
```

The v5 public model exposes `FlowPlan.flow`, compact `document` and `linguistics` records, and local segment fields for text, language, directives, pause intent, markers, headings, and tokens. `FlowSegment.directives` contains typed semantics after scope and voice-default resolution. `TokenView` offsets address only its owning segment's text; provider documents are not retained. See the [consumer guide](consumer-guide) for renderer responsibilities.

`TokenView` carries optional lemma, POS, tag, and morph facts. `LinguisticProvenance` identifies the analysis provider and model without retaining provider state. Source spans, exact source text, and preparation coordinate maps are available only in an optional `PreparationTrace` sidecar, not the plan TOML.

## Errors

Planning and loading failures derive from `utterplan.UtterPlanError`. Important
public subclasses include `ConfigurationError`, `PlanningError`,
`PlanFormatError`, `PlanValidationError`, and `UnsupportedSchemaError`.
`PlanMigrationError` and `MigrationPathError` report migration-specific failures. `UnsupportedSchemaError` remains reserved for a schema newer than the installed package understands.

`PlanRenderabilityError` presents the same actionable source and spoken context as the CLI, including safe repair opportunities, semantic blockers, and a next action. Safe punctuation-only repair is the default; choose `PlannerConfig(renderability_mode="strict")` when a caller needs to reject every repair opportunity. Symbols are never assigned guessed pronunciations.

## Schema migration API

```python
from utterplan import (
    FlowPlan,
    CURRENT_SCHEMA_VERSION,
    MigrationResult,
    MigrationStep,
    SUPPORTED_SCHEMA_VERSIONS,
    migrate_plan_data,
)

result: MigrationResult = migrate_plan_data(serialized_mapping)
assert result.target_version == CURRENT_SCHEMA_VERSION
plan = FlowPlan.from_dict(result.data)
```

Migration functions operate on plain JSON-compatible mappings and never mutate their input. `MigrationResult` records source and target versions, sequential steps, and source and target plan IDs. Current-schema migration is an exact no-op.
