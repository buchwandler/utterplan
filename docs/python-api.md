# Python API

The canonical public entry point is `compile_document`, which compiles one SSMD
document or explicitly configured plain-text document and returns a `CompileResult`.
Its `plan` is the immutable, round-trippable renderer-independent `UtterancePlan`;
its `diagnostics` explain compilation, and an optional `PreparationTrace` is
separate diagnostic output. `UtterancePlanner.plan` remains supported for
compatibility and returns only the plan.

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
assert result.diagnostics == plan.diagnostics
assert result.trace is not None
```

Use `input_format="plain"` only for explicitly configured plain text. A trace
contains explanatory per-unit preparation information but is not serialized into
the plan, is not renderer input, and does not change `plan.plan_id`. Its source
ranges index SSMD-clean structural text; transformation output ranges index prepared
spoken text, using Python string character offsets.

## TOML persistence

Schema v4 remains the semantic contract, while `.utterplan.toml` is the canonical persisted format. `to_toml()` and `from_toml()` round-trip the complete plan; `save()` writes atomically, and `load()` accepts TOML only. Normal loading does not auto-detect or fall back to JSON.

```python
from utterplan import UtterancePlan

toml_text = plan.to_toml()
restored = UtterancePlan.from_toml(toml_text)
assert restored == plan
plan.save("chapter.utterplan.toml")
assert UtterancePlan.load("chapter.utterplan.toml") == plan
```

`to_dict()` and `from_dict()` remain semantic mapping APIs. For a legacy JSON file, use the explicit `utterplan migrate old.utterplan.json -o current.utterplan.toml` command; SSMD source migration is a separate operation.

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

The report is operational data, not a semantic plan, and must not be passed to `UtterancePlan.load()`. Unexpected programming and progress-callback errors propagate rather than being converted to document failures.

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

The SSMD parser accepts dialect 0.9 only. Select SSMD explicitly for unversioned canonical fragments with `PlannerConfig(document_format="ssmd")`. Older SSMD source must be migrated with `ssmd migrate FILE --to 0.9`; `migrate_plan_data` operates on serialized plan mappings, while `utterplan migrate` explicitly imports legacy JSON plan files into canonical TOML, not source documents.

`PlannerConfig.document_format` defaults to `"plain"`, so SSMD syntax is never inferred for an ordinary Python string. Set `document_format="ssmd"` for SSMD documents or fragments.

`SSMDConfig.parse_yaml_header` controls front-matter parsing. The ineffective `strict_header` and `unknown_header` options were removed because SSMD 0.9 owns header validation. Application pause settings use `SSMDConfig.pause_overrides`; this is distinct from the portable source-header key `pause_defaults`. At a shared boundary, an explicit SSMD break takes precedence, followed by the application override, document defaults, and planner defaults.

```python
from utterplan import PlannerConfig, UtterancePlanner

ssmd_source = """---
ssmd_version: "0.9"
title: API example
language: en-us
---
Hello [world]{emphasis="strong"}.
"""

planner = UtterancePlanner(
    PlannerConfig(language="en-us", document_format="ssmd")
)
plan = planner.plan(ssmd_source)

assert plan.document_metadata["ssmd_version"] == "0.9"
annotation = plan.annotations[0]
print(annotation.source_start, annotation.source_end, annotation.source_node_id)
directives = plan.segments[0].directives
print(directives.voice, directives.prosody, directives.say_as)
```

SSMD annotations preserve declared source spans. Segment directives hold effective typed semantics after scope and voice-default resolution. `document_metadata` preserves portable header data and the SSMD version; `plan.boundaries` preserves heading events. Audio references and extension names are not executed by UtterPlan. See the [coordinate-space contract](coordinate-spaces) for source offset units and the [consumer guide](consumer-guide) for renderer responsibilities.

## Semantic boundaries

`SemanticBoundary` is an immutable, engine-neutral split opportunity. Its
`position` is always in `plan.texts.spoken`, and its `kind` distinguishes clause,
parenthetical, sentence, and paragraph structure. It is intentionally separate
from `BoundaryEvent`: semantic boundaries do not carry pause duration or depend
on whether a pause policy activates an event.

```python
from utterplan import SemanticBoundary

for boundary in plan.semantic_boundaries_for_segment(segment, kinds={"clause"}):
    offset = boundary.position - segment.spoken_start
    left, right = segment.text[:offset], segment.text[offset:]
```

Use `semantic_boundaries_in_range(start, end)` when lowering a plan into a
request-local renderer capacity. Do not import parser/provider documents or
recompute clause analysis in the consumer.

## Audio/media segments

`AudioDirective` is already part of the public API. Inspect it on the segment; its
`src` is an opaque renderer input, and `segment.text` is optional spoken fallback:

```python
segment = plan.segments[0]
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

```{autoclass} utterplan.UtterancePlan
:members:
:show-inheritance:
```

```{autoclass} utterplan.PlanSegment
:members:
:show-inheritance:
```

```{autoclass} utterplan.PlanUnit
:members:
:show-inheritance:
```

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

The public model also exposes `languages`, `annotations`, `boundaries`,
`tokens`, `markers`, `document_metadata`, and resolved segment pauses. See the
[consumer guide](consumer-guide) for how a renderer uses these fields.

`TokenAnnotation` contains `text`, `language`, `lemma`, `pos`, `tag`, and `morph`. Token text and offsets address `texts.spoken`; `morph` is a compact provider string such as `Tense=Pres|VerbForm=Fin`. `LinguisticRun` records whether those facts came from spaCy, fallback tokenization, or unknown legacy provenance.

`TextPreparationInfo` exposes serializable provenance only. Exact source-to-spoken mapping is transient planner state and is not part of `UtterancePlan` or its TOML contract.

## Errors

Planning and loading failures derive from `utterplan.UtterPlanError`. Important
public subclasses include `ConfigurationError`, `PlanningError`,
`PlanFormatError`, `PlanValidationError`, and `UnsupportedSchemaError`.
`PlanMigrationError` and `MigrationPathError` report migration-specific failures. `UnsupportedSchemaError` remains reserved for a schema newer than the installed package understands.

`PlanRenderabilityError` presents the same actionable source and spoken context as the CLI, including safe repair opportunities, semantic blockers, and a next action. Safe punctuation-only repair is the default; choose `PlannerConfig(renderability_mode="strict")` when a caller needs to reject every repair opportunity. Symbols are never assigned guessed pronunciations.

## Schema migration API

```python
from utterplan import (
    CURRENT_SCHEMA_VERSION,
    MigrationResult,
    MigrationStep,
    SUPPORTED_SCHEMA_VERSIONS,
    migrate_plan_data,
 )

result: MigrationResult = migrate_plan_data(serialized_mapping)
assert result.target_version == CURRENT_SCHEMA_VERSION
plan = UtterancePlan.from_dict(result.data)
```

Migration functions operate on plain JSON-compatible mappings and never mutate their input. `MigrationResult` records source and target versions, sequential steps, and source and target plan IDs. Current-schema migration is an exact no-op.
