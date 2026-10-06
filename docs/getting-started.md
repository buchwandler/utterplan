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

print(plan.texts.spoken)
for segment in plan.segments:
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

The default compile policy is `spokenform` for text preparation, `tts` for pause mode, and `spacy off` for linguistic resources. The fallback path records `linguistic_runs[*].provider = "fallback"` and leaves POS, tag, and morph unavailable. It does not require an installed spaCy model.

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

The compiled plan preserves SSMD header metadata, declared annotations, structural events, and effective typed directives. Audio and extension references are descriptive data only; consumers decide how to interpret them.
Structural text preserves the parsed document representation. Spoken text is
the prepared text and is the coordinate space used by segments, tokens,
markers, boundaries, and renderer-facing ranges.
Inspect safe spoken-text subdivision opportunities separately from pause and
timing events:

```bash
utterplan inspect hello.utterplan.toml --semantic-boundaries
```

Use `plan.semantic_boundaries` or the public
`semantic_boundaries_for_segment()` / `semantic_boundaries_in_range()` helpers.
They expose clause, parenthetical, sentence, and paragraph opportunities without
requiring SSMD, spaCy, Phrasplit, or renderer-specific packages.
