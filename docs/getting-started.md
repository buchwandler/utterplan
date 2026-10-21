# Getting started

## Install

Install the package from the distribution that matches your environment:

```bash
python -m pip install utterplan
```

For development, install the test and documentation extras from a checkout:

```bash
python -m pip install -e '.[dev,docs]'
```

## Create a plan in Python

```python
from utterplan import PlannerConfig, UtterancePlanner

planner = UtterancePlanner(PlannerConfig(language="en-us"))
plan = planner.plan("Doctor Smith bought 5 kg of apples.")

for unit in plan.flow:
    for segment in unit.segments:
        print(segment.text, segment.language)
```

Python `PlannerConfig` defaults to plain input. Pass `document_format="ssmd"` when planning SSMD source from Python.
The planner produces semantic information for a renderer. It does not produce
phonemes, model tokens, or audio.

## Compile literal text

```bash
utterplan compile "Doctor Smith bought 5 kg." --lang en-us
```

Without `-o`, the complete canonical TOML plan is written to stdout. Status messages use stderr, so redirecting stdout creates a valid plan file:

## Defaults and linguistic resources

Text preparation defaults to `auto`: plain text resolves to TTSReady/Spokenform, while SSMD resolves to authoritative `ssmd` mode and consumes reviewed `sub` aliases without another automatic preparation pass. Explicit `spokenform` on SSMD is a warned legacy mode. There is no compile-time pause activation or renderer chunking choice; safe boundary opportunities and authored pauses are stored separately for downstream use. SpaCy uses best-effort `auto` with deterministic fallback; UtterPlan never downloads models.

Use `--spacy off` to force fallback, or `--spacy sm|md|lg|trf` to require a specific local tier. Python `LinguisticsConfig` has the same best-effort default. Install the optional library with `python -m pip install 'utterplan[spacy]'` when needed; install language model packages separately.
Language model packages remain explicit environment dependencies; UtterPlan never downloads them.

Final v7 token fields (`pos`, `tag`, `lemma`, and `morph`) describe prepared segment text and are the downstream linguistic context, not engine/model token counts. Optional replacement spans are local to that final text; preserve the trace sidecar for full source-coordinate maps and preparation diagnostics.

```bash
utterplan compile "Hello world." --lang en-us -o hello.utterplan.toml
utterplan inspect hello.utterplan.toml --segment 0
```

## Compile stdin or a file

````bash
echo "Hello world." | utterplan compile --lang en-us > hello.utterplan.toml
utterplan compile chapter.ssmd.md --lang en-us -o chapter.utterplan.toml
utterplan compile --file chapter.ssmd.md --lang en-us -o chapter.utterplan.toml

A single existing positional path is read as a file. Use
`--input-format text` when a path-like value must remain literal text.

## Compile many documents

`compile-many` writes one canonical plan per source and commits each successful result immediately. By default it continues after ordinary failures, preserving earlier outputs; progress, actionable diagnostics, repair notices, and a final summary go to stderr.

```bash
utterplan compile-many chapters/*.ssmd --output-dir build/plans
````

Each output name is derived from its source (`chapter.ssmd` becomes `chapter.utterplan.toml`). The command atomically refreshes `build/plans/compile-report.toml`; use `--report PATH` to choose another location, `--fail-fast` to skip later inputs after a failure, and `--force` to replace existing plans. Duplicate output names and report/output collisions are rejected before writing.

## Compile from a bundle

Book and single-document bundles use the same manifest-driven command. The canonical input is a directory named `<name>.ssmd-bundle/`; UtterPlan determines the kind from `manifest.json`.

```bash
utterplan bundle compile "Platform Decay - Martha Wells.ssmd-bundle" --chapters 5-17
utterplan bundle compile story.ssmd-bundle
```

Compilation writes one independent schema-v7 FlowPlan per selected item and an operational report under `<bundle>/utterplan/`. Book selectors use manifest source numbers: omit `--chapters` for all chapters, or use a range such as `5-17` or comma-separated selection such as `1,3-5`. A document bundle supports only `--chapters all`. Source manifests and documents remain unchanged. See the [bundle guide](bundles.md) for layouts and safety details.

Safe punctuation repair is enabled by default for standalone `compile` and `compile-many`. Use `--renderability strict` to reject repair opportunities and inspect their explanation without modifying a plan.

## Project a bundle for a profile

Create and validate a RenderProfile with VoiceRender, then project saved bundle plans:

```bash
voicerender profile create \
  --engine piper --target en_US-amy-medium --language en-US \
  --offline --output narration.renderprofile.toml
utterplan bundle render "Platform Decay - Martha Wells.ssmd-bundle" \
  --chapters 5-17 --profile narration.renderprofile.toml
utterplan bundle render story.ssmd-bundle --profile narration.renderprofile.toml
```

The resulting profile-specific RenderPlans are written below `<bundle>/renderplan/`; canonical plans and source content remain untouched. VoiceRender is responsible for downstream preflight, synthesis, and audio. See the [bundle guide](bundles.md), [VoiceRender](https://pypi.org/project/voicerender/), and [RenderPlan](https://pypi.org/project/renderplan/).

## Inspect and validate

```bash
utterplan validate hello.utterplan.toml
utterplan inspect hello.utterplan.toml --segment 0
utterplan inspect hello.utterplan.toml --unit 0 --boundaries --tokens
```

`inspect --unit` only selects a saved flow unit for inspection; it is not a compile-time renderer grouping option.

## SSMD

SSMD is selected by `.ssmd` or `.ssmd.md` suffixes, an SSMD version header in Markdown, or explicitly from stdin:

```bash
printf '[Hello]{lang="en-us"} ...s [Bonjour]{lang="fr"}.\n' \
  | utterplan compile --lang en-us --input-format ssmd
```

UtterPlan parses SSMD dialect 0.9 only, including canonical fragments without a version header when explicitly selected. Older SSMD source must be converted first: `ssmd migrate old.ssmd --to 0.9`. `utterplan migrate` handles serialized-plan migration only; v6-to-v7 promotion may return `migration.recompile_required`, in which case recompile the original source. It does not migrate source files.

The compiled plan preserves compact document metadata, exact raw source in the optional v7 `source` record, effective directives, canonical boundary opportunities, and authored pause intent. Audio and extension references are descriptive data only; consumers decide how to interpret them.

The v7 plan stores exact raw input once in an optional source record, plus prepared segment text, local token spans, and compact replacement views. It does not store structural text or dense source/preparation maps; preserve an optional trace sidecar for those details:

```bash
utterplan compile chapter.ssmd.md -o chapter.utterplan.toml --trace chapter.trace.toml
utterplan explain chapter.utterplan.toml --trace chapter.trace.toml
utterplan inspect-trace chapter.trace.toml --preparation --boundaries
```

Trace data contains source text/hash, preparation maps, diagnostics, and renderability evidence. Exact raw input is also stored in the optional v7 plan source record; trace data does not change plan TOML or identity. Segment token offsets are local Python-character ranges into each owning segment's `text`.
