[![PyPI - Version](https://img.shields.io/pypi/v/utterplan)](https://pypi.org/project/utterplan/)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/utterplan)
![PyPI - Downloads](https://img.shields.io/pypi/dm/utterplan)
[![codecov](https://codecov.io/gh/buchwandler/utterplan/graph/badge.svg?token=cL0qStxvDE)](https://codecov.io/gh/buchwandler/utterplan)

# UtterPlan

UtterPlan is the canonical, engine-independent semantic compiler from one SSMD
document (or explicitly selected plain-text document) to an executable speech
plan. It produces deterministic prepared text, paragraph-local flow units, safe
boundary opportunities, authored pause intents, segment-local semantics,
portable document metadata, and typed directives for independent downstream
FlowPlan consumers. Its `bundle` lifecycle accepts canonical `.ssmd-bundle/`
roots and dispatches book or document behavior from `manifest.json`, without
modifying source manifests or chapters. It uses TTSReady for written-to-spoken
preparation and stops before G2P, synthesis, and audio.

## CLI

Compile literal text directly:

```bash
utterplan compile "Doctor Smith bought 5 kg." --input-format plain --language en-us
```

Compile a file to a plan file:

```bash
utterplan compile examples/chapter.ssmd -o chapter.utterplan.toml
```

SSMD header `language` is authoritative, so `--language` is optional when it is present. Otherwise pass `--language` as the fallback; plain input always requires a language. `--language` never forces a language over SSMD semantics.

Use stdin and shell pipelines:

```bash
cat examples/chapter.ssmd | utterplan compile --lang en-us --input-format ssmd > chapter.utterplan.toml
```

Compile independent documents incrementally; every successful plan is saved immediately, and ordinary failures do not discard earlier outputs:

```bash
utterplan compile-many examples/*.ssmd --output-dir build/plans
```

This writes one `.utterplan.toml` per source plus an atomically refreshed `compile-report.toml`. Terminal diagnostics default to warnings; `--diagnostics all` also prints informational records, while `--diagnostics none` suppresses non-failure details. Failures are always reported, and the operational report retains every diagnostic. Use `--fail-fast` to skip later inputs after a failure, `--force` to replace existing plans, or `--report PATH` to choose another report location.

## Manifest-driven bundle lifecycle

Use the canonical `<name>.ssmd-bundle/` directory for either a book or a single-document bundle. UtterPlan reads `manifest.json` to determine the bundle kind; chapter directories and source files are not alternate bundle roots.

```bash
utterplan bundle compile novel.ssmd-bundle --chapters 5-17
utterplan bundle compile story.ssmd-bundle
utterplan bundle render novel.ssmd-bundle --chapters 5-17 --profile narration.renderprofile.toml
utterplan bundle render story.ssmd-bundle --profile narration.renderprofile.toml
```

Book manifests support source-number selectors such as `5-17` or `1,3-5`; omit `--chapters` to select all chapters. A document bundle accepts only `--chapters all`. Compilation writes independent FlowPlans and an operational report under `<bundle>/utterplan/`; rendering projects saved plans into profile-specific RenderPlans under `<bundle>/renderplan/`. Source manifests and source documents remain untouched. See the [bundle guide](docs/bundles.md) for manifest contracts, safe paths, reports, and examples.

When rendering feedback requests deterministic replanning, refine the active bundle variant and the selected book items (or the full document bundle):

```bash
utterplan bundle replan novel.ssmd-bundle --chapters 5 --variant narration--28f616b6fe3b
```

Replanning uses stored profile snapshots and matching preflight feedback; it does not run synthesis or modify source content.

## Logical roles and complete RenderProfiles

An SSMD `voice` reference is a **logical role**: a renderer-independent name such as `narrator`, `host`, or `guest`. A **role binding** is the concrete renderer configuration for that name in a RenderProfile. One RenderProfile is the complete cast for one render variant, together with shared planning and pause policy; it may bind different roles to different engines. UtterPlan accepts one `--profile` per projection, not one profile per role, and does not discover engines or voices.

A profile can define a default for speech without an explicit role reference and explicit bindings for other roles:

In SSMD, the source remains renderer-independent; for example:

```markdown
:::{voice="host"}
Host line.
:::
```

```toml
default_role = "narrator"

[roles.narrator]
language = "en-US"

[roles.narrator.binding]
renderer = "kokoro"
target_id = "v1.0"
voice = "af_heart"

[roles.host]
language = "en-US"

[roles.host.binding]
renderer = "kitten"
target_id = "mini-0.8"
voice = "Jasper"

[roles.guest]
language = "en-US"

[roles.guest.binding]
renderer = "piper"
target_id = "en_US-amy-medium"
voice = "en_US-amy-medium"
```

Inspect symbolic role usage without a profile, then project a document or selected book chapters with the same complete cast:

```bash
utterplan inspect story.utterplan.toml --roles
utterplan bundle render story.ssmd-bundle --profile printer-cast.renderprofile.toml
utterplan bundle render novel.ssmd-bundle --profile novel-cast.renderprofile.toml
```

Projection reports required and available roles and rejects incomplete coverage before writing the RenderPlan variant. The profile and its concrete role bindings remain separate from the source SSMD.

## From bundles to RenderPlans

UtterPlan keeps one canonical semantic plan per source item. A RenderProfile is a
separate renderer configuration; create and validate it with VoiceRender, then
project saved plans from a canonical `.ssmd-bundle/` root:

```bash
voicerender profile create \
  --engine piper \
  --target en_US-amy-medium \
  --language en-US \
  --offline \
  --output narration.renderprofile.toml
voicerender profile validate narration.renderprofile.toml

utterplan bundle compile novel.ssmd-bundle --chapters 5-17
utterplan bundle render novel.ssmd-bundle --chapters 5-17 --profile narration.renderprofile.toml
```

The shared `renderplan/` area contains a profile-specific variant:

```text
renderplan/
└── narration--<profile-fingerprint>/
    ├── renderprofile.toml
    ├── renderplan-set.toml
    ├── render-report.toml
    ├── chapter-0005.renderplan.toml
    └── ...
```

The variant label comes from the profile filename by default; its suffix is the
first 12 hexadecimal characters of the canonical RenderProfile `profile_id`.
Changing identity-bearing profile semantics selects a different directory, so
multiple voices or planning policies can coexist without replacing one another.
Each variant snapshots the canonical profile; `renderplan-set.toml` records its
full identity, source profile reference, and source plan IDs. `--variant` changes
the human label without removing the fingerprint, and `--output-root` changes the
collection root while retaining the automatic variant directory.

`utterplan bundle render` consumes only existing schema-v7 FlowPlans and the
shared RenderProfile/RenderPlan contract. VoiceRender creates or refreshes
engine-backed profiles, then preflights and renders the resulting RenderPlans.
UtterPlan's single-file `render-plan` command remains the low-level projection and
deterministic replan primitive.

Character-spelling segments keep exact identity in their portable token lemmas: a single alphanumeric token under `say_as = {interpret_as = "characters"}` has the exact token surface as its lemma, even when a linguistic provider reports a context-sensitive lowercase lemma. Ordinary lexical lemmas retain compact casefold-default encoding. Newly generated RenderPlans use schema v2 and store each used role's concrete configuration once in a top-level `[bindings.<role>]` table. The RenderPlan codec restores the complete `SpeechItem.binding` mapping on load; this changes disk layout, not the consumer API.

### Troubleshooting RenderProfile identity mismatch

A RenderProfile `profile_id` is a semantic content identity validated by RenderPlan; it is not a hash of the TOML file bytes. If the profile's identity-bearing semantics change without refreshing its ID, UtterPlan rejects it before creating RenderPlan artifacts. Regenerate or re-save the complete profile with VoiceRender, then validate it before rendering:

```bash
voicerender profile validate narration.renderprofile.toml
```

Do not replace `profile_id` with `sha256sum` of the TOML file. `--force` only replaces an otherwise valid existing RenderPlan output; it never bypasses profile validation.

When VoiceRender reports `preflight.replan`, refine the active bundle variant
using matching feedback:

```bash
# After VoiceRender reports preflight.replan for chapter 5:
utterplan bundle replan novel.ssmd-bundle \
  --variant narration--28f616b6fe3b \
  --chapters 5
```

Ask VoiceRender to measure and render the newly active plan. If it still reports
`preflight.replan`, repeat the feedback cycle against the active child.

Use the exact variant directory name (including its profile fingerprint). Bundle
replanning searches `preflight-recheck.toml` before `preflight.toml` and refuses
stale feedback, so a report for a parent can never be applied to its child. The
single-file `render-plan --previous ... --preflight ...` operation remains available for
low-level replanning.

This orchestration does not add a splitter, renderer-specific capacity estimate, or
engine dependency. VoiceRender supplies preflight measurements and remains responsible
for synthesis and audio composition.

Related packages: [RenderPlan](https://pypi.org/project/renderplan/) defines the
shared profile and plan contracts; [VoiceRender](https://pypi.org/project/voicerender/)
creates engine-backed profiles and performs preflight and synthesis.

The CLI also provides:

```bash
utterplan --version
utterplan validate chapter.utterplan.toml
utterplan inspect chapter.utterplan.toml --segment 0
utterplan inspect chapter.utterplan.toml --boundaries --tokens
utterplan explain chapter.utterplan.toml --trace chapter.trace.toml
utterplan inspect-trace chapter.trace.toml --preparation --boundaries
utterplan inspect-attempt chapter.attempt.toml --issues
utterplan preview chapter.utterplan.toml --segments 58-62 --chunk-by clause --pause-policy automatic
utterplan render-plan chapter.utterplan.toml --profile voice.renderprofile.toml -o chapter.renderplan.toml --explain
```

`explain` presents executable flow as a human-readable speech plan. Use `compile --trace PATH` to retain optional compiler provenance; `explain --trace PATH` and `inspect-trace` read that sidecar separately from the plan.

`render-plan` projects only current schema-v7 FlowPlans into the shared RenderPlan contract. Replanning requires both the exact previous RenderPlan and its matching preflight report; UtterPlan refines only failed speech occurrences and does not calculate renderer-specific metrics.

`inspect-attempt` reads the separate `utterplan.planning-attempt.v1` TOML artifact,
not a canonical plan. Use it to review renderability issues and safe repair
assessments on blocked planning outcomes; such candidates remain inspect-only drafts.
Canonical plan output is TOML (`.utterplan.toml`) and is written to stdout when no output file is supplied. Status messages use stderr, and existing output files require `--force`. Safe punctuation repair is the default; use `--renderability strict` to reject every repair opportunity.

## SSMD source contract

UtterPlan accepts SSMD 0.9 syntax only. Use `document_format="ssmd"` or
`--input-format ssmd` to compile canonical unversioned fragments as SSMD 0.9.
Automatic detection recognizes `.ssmd`, `.ssmd.md`, and Markdown files with an SSMD
version header; ordinary Markdown remains plain text.

Migrate older SSMD source before compilation with the SSMD project's migration
command:

```bash
ssmd migrate old.ssmd --to 0.9
```

`utterplan migrate` handles only serialized plan data; v6-to-v7 migration refuses with `migration.recompile_required` when the saved plan cannot prove complete boundary coverage. Recompile the original source to produce a current plan. It does not migrate SSMD source.
Normal plan loading is TOML-only: `FlowPlan.load()` and plan-inspection commands reject JSON rather than auto-detecting it.

## Planning defaults

The CLI and Python planner default to best-effort spaCy enrichment (`auto`). UtterPlan prefers an already-installed compatible model in `sm`, `md`, `lg`, `trf` order; if spaCy or every compatible local model is unavailable, planning continues with deterministic fallback tokens. UtterPlan never downloads models. Use `--spacy off` or `LinguisticsConfig(use_spacy=False)` to opt out, or request an explicit tier to require that local model.

Python `PlannerConfig` defaults to `document_format="plain"`; set it to `"ssmd"` when a Python string contains SSMD source.

Python `PlannerConfig.renderability_mode` also defaults to safe punctuation-only repair; choose `"strict"` to reject every repair opportunity. Neither mode guesses a symbol's pronunciation or crosses semantic blockers.

V7 `token.span`, `pos`, `tag`, `lemma`, and `morph` describe the prepared `segment.text` and are the downstream linguistic context, not engine/model token counts; consumers should not retokenize or rerun spaCy. Optional `replacement.span` / `replacement.source` records compact preparation provenance (for example, `A R T` from `ART`): spans index final prepared segment text, while full source coordinates and maps remain in the optional trace sidecar. Replacement provenance does not change executable hashes or synthesis inputs.

## Python API

```python
from utterplan import PlannerConfig, FlowPlan, compile_document

ssmd_source = """---
ssmd_version: "0.9"
language: en-GB
---
Hello [world]{emphasis="strong"}.
"""
result = compile_document(
    ssmd_source,
    input_format="ssmd",
    config=PlannerConfig(language="en-us"),  # fallback; header language wins
    trace=True,
)
plan = result.plan
assert result.trace is not None
plan.save("example.utterplan.toml")
assert FlowPlan.load("example.utterplan.toml") == plan
```

`compile_document` is the stable public one-document API shared by consumers. The
immutable `CompileResult` contains the semantic plan, diagnostics, and optional
explanatory trace. Trace is not serialized in the plan and does not affect its
identity. Plain text must be explicitly selected in Python and always requires a
language fallback. Existing `UtterancePlanner.plan` remains supported and returns
only the plan; TOML is the portable persistence and interchange format.

The optional RenderPlan producer consumes the stored prepared plan directly:

```python
from renderplan.codec import load_profile, save_plan
from utterplan import FlowPlan, build_render_plan

source = FlowPlan.load("chapter.utterplan.toml")
profile = load_profile("voice.renderprofile.toml")
render_plan = build_render_plan(source, profile)
save_plan(render_plan, "chapter.renderplan.toml")
```

Use `build_render_plan(..., previous_plan=previous, preflight=report)` for deterministic refinement; both values are required together. The RenderPlan path rejects historical UtterPlan schemas and does not depend on a renderer or audio runtime. See the [RenderPlan CLI](docs/cli.md#produce-or-replan-a-renderplan) and [Python API](docs/python-api.md#build-and-replan-a-renderplan) guides.

For operational progress from a long-running Python plan, pass `on_progress` to
`UtterancePlanner.plan`, `UtterancePlanner.compile`, or `compile_document`. The
callback receives typed `PlannerProgressEvent` objects and does not change the plan:

```python
from utterplan import PlannerConfig, UtterancePlanner

events = []
plan = UtterancePlanner(PlannerConfig(language="en-us")).plan(
    text,
    on_progress=events.append,
)
```

Callbacks run synchronously and exceptions propagate. See the [Python API guide](docs/python-api.md#planner-progress-callbacks) for event fields, model-load events, and reuse behavior.

## Renderer-consumer boundary

Renderers consume `FlowPlan.flow` in order. Each `FlowUnit` contains local `FlowSegment` objects with already-prepared speech text, effective language, segment-local linguistic token views, canonical boundary opportunities, authored pause intents, directives, markers, and optional heading level. Token `start`/`end` offsets are Python-character indexes into that segment's `text`; they are never document-global coordinates. FlowUnits are fixed paragraph-local blocks, not renderer chunks; a `FlowSegment` is not necessarily one TTS call. `boundary_before` / `boundary_after` hold safe cut opportunities independently from authored `none`, strength, or timed pause intents. Consumers may choose sentence, paragraph, or engine-token-budget chunking and native, automatic, or manual pause realization; linguistic token views are not model-token counts.

For renderer-neutral chunk tests and debugging, `preview_plan()` projects stored text and boundaries without changing the plan:

```python
from utterplan import FlowPlan, preview_plan

plan = FlowPlan.load("chapter.utterplan.toml")
chunks = preview_plan(plan, chunk_by="clause", pause_policy="automatic")
```

`FlowPlan.document` carries compact document metadata and `FlowPlan.linguistics` identifies the analysis provider without retaining provider documents. Compiler source, preparation maps, diagnostics, and renderability details belong only in an optional trace sidecar. Plans contain no phonemes, model token IDs, models, sessions, renderer configuration, provider documents, or audio. UtterPlan does not fetch media or execute extension handlers.
The intended dependency direction is:

```text
PyKokoro or another renderer -> UtterPlan
```

UtterPlan does not depend on PyKokoro, G2P engines, ONNX Runtime, or audio
packages. Consumer-specific compatibility tests belong in the consuming
renderer repository rather than UtterPlan's test suite.

## Documentation

- [Getting started](docs/getting-started.md)
- [CLI](docs/cli.md)
- [Bundle workflows](docs/bundles.md)
- [Format and schema](docs/format.md)
- [Consumer guide](docs/consumer-guide.md)
- [Architecture](docs/architecture.md)
- [Coordinates](docs/coordinate-spaces.md)
- [PyKokoro integration](docs/pykokoro-integration.md)
- [Python API](docs/python-api.md)
- [Debugging](docs/debugging.md)
- [Changelog](docs/changelog.md)

## Versions

The package version is dynamically derived from Git tags by setuptools-scm. Package version and UtterPlan schema version are independent. Current `.utterplan.toml` plans use semantic schema v7. Historical JSON Schemas v1–v4 remain immutable; schemas v5, v6, and v7 use versioned TOML/FlowPlan contracts and have no JSON Schema resources.

Schema v5 introduced ordered flow units and segment-local semantics; v6 added optional exact-source provenance. Schema v7 removes renderer-selected root `unit` and adds canonical safe-boundary opportunities separate from authored pause intents; boundaries participate in v7 executable identity. Older schemas retain sequential data-only migration steps through v6, but v6-to-v7 returns `migration.recompile_required` because the complete boundary inventory cannot be reconstructed. Migrations never reparse, run NLP, plan, call G2P, render, or process audio.

## Development

```bash
python -m pip install -e '.[dev,docs]'
python -m pytest -q
ruff check .
mypy utterplan
python -m build
sphinx-build -W --keep-going -b html docs docs/_build/html
```
