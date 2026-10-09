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

The default compile policy is `spokenform` for text preparation, `tts` for pause activation, and `spacy off` for linguistic resources. The fallback path records `linguistics[*].provider = "fallback"` and leaves unavailable POS, tag, and morphology empty. It does not require an installed spaCy model.

`--spacy auto` is an explicit opt-in. With a compatible local model, final pass-B tokens may contain POS, tag, lemma, and morphology, and the plan records the actual provider, model, and known versions. `sm`, `md`, `lg`, and `trf` require the requested local model. UtterPlan never downloads models automatically.
Install the optional library with `python -m pip install 'utterplan[spacy]'` when needed. Language model packages remain explicit environment dependencies and are never downloaded by UtterPlan.

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

## Compile chapters from an SSMDBook

For an editable `.ssmdbook` directory, compile a source-number range without expanding filenames in the shell:

```bash
cd "Platform Decay - Martha Wells.ssmdbook"

utterplan compile-book chapters --chapters 5-17
```

This writes one independent canonical v5 plan per selected chapter and a TOML report by default:

```text
utterplan/
├── compile-report.toml
├── chapter-0005.utterplan.toml
├── chapter-0006.utterplan.toml
├── ...
└── chapter-0017.utterplan.toml
```

Omit `--chapters` to compile all manifest chapters. Select non-contiguous chapters with a comma-separated selector, for example `utterplan compile-book chapters --chapters 1,3-5`. You can also pass the `.ssmdbook` root instead of `chapters/`, and override the destination with `--output-dir build/plans`. UtterPlan reads the manifest and current selected chapter content but does not modify the book or refresh stale chapter hashes. See the [SSMDBook guide](ssmdbook.md) for selection rules and safety details.
Safe punctuation repair is enabled by default for both `compile` and `compile-many`. Use `--renderability strict` to reject repair opportunities and inspect their explanation without modifying the plan.

## Inspect and validate

````bash
utterplan validate hello.utterplan.toml
utterplan inspect hello.utterplan.toml --segment 0
utterplan inspect hello.utterplan.toml --unit 0 --boundaries --tokens

## SSMD

SSMD is selected by `.ssmd` or `.ssmd.md` suffixes, an SSMD version header in Markdown, or explicitly from stdin:

```bash
printf '[Hello]{lang="en-us"} ...s [Bonjour]{lang="fr"}.\n' \
  | utterplan compile --lang en-us --input-format ssmd
````

UtterPlan parses SSMD dialect 0.9 only, including canonical fragments without a version header when explicitly selected. Older SSMD source must be converted first: `ssmd migrate old.ssmd --to 0.9`. `utterplan migrate` explicitly imports historical UtterPlan JSON plans into TOML; it does not migrate source files.

The compiled plan preserves compact document metadata, effective directives, and semantic pause intent. Audio and extension references are descriptive data only; consumers decide how to interpret them.

The plan stores prepared segment text and local token spans, not source-level structural text or dense maps. Preserve compiler details in an optional trace sidecar:

```bash
utterplan compile chapter.ssmd.md -o chapter.utterplan.toml --trace chapter.trace.toml
utterplan explain chapter.utterplan.toml --trace chapter.trace.toml
utterplan inspect-trace chapter.trace.toml --preparation --boundaries
```

Trace data contains source text/hash, preparation maps, diagnostics, and renderability evidence. It does not change plan TOML or identity. Segment token offsets are local Python-character ranges into each owning segment's `text`.
