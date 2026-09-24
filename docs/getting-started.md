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

Without `-o`, the complete plan JSON is written to stdout. This makes the
result convenient for shell pipelines:

## Defaults and linguistic resources

The default compile policy is `spokenform` for text preparation, `tts` for pause mode, and `spacy off` for linguistic resources. The fallback path records `linguistic_runs[*].provider = "fallback"` and leaves POS, tag, and morph unavailable. It does not require an installed spaCy model.

`--spacy auto` is an explicit opt-in. With a compatible local model, final pass-B tokens may contain POS, tag, lemma, and morphology, and the plan records the actual provider, model, and known versions. `sm`, `md`, `lg`, and `trf` require the requested local model. UtterPlan never downloads models automatically.
Install the optional library with `python -m pip install 'utterplan[spacy]'` when needed. Language model packages remain explicit environment dependencies and are never downloaded by UtterPlan.

```bash
utterplan compile "Hello world." --lang en-us | jq '.segments'
```

## Compile stdin or a file

```bash
echo "Hello world." | utterplan compile --lang en-us > hello.utterplan.json
utterplan compile chapter.ssmd.md --lang en-us -o chapter.utterplan.json
utterplan compile --file chapter.ssmd.md --lang en-us -o chapter.utterplan.json
```

A single existing positional path is read as a file. Use
`--input-format text` when a path-like value must remain literal text.

## Inspect and validate

```bash
utterplan validate hello.utterplan.json
utterplan inspect hello.utterplan.json --segment 0
utterplan inspect hello.utterplan.json --unit 0 --boundaries --tokens
```

## SSMD

SSMD is selected by `.ssmd` or `.ssmd.md` suffixes, an SSMD version header in Markdown, or explicitly from stdin:

```bash
printf '[Hello]{lang="en-us"} ...s [Bonjour]{lang="fr"}.\n' \
  | utterplan compile --lang en-us --input-format ssmd
```

UtterPlan parses SSMD dialect 0.9 only, including canonical fragments without a version header when explicitly selected. Older SSMD source must be converted first: `ssmd migrate old.ssmd --to 0.9`. `utterplan migrate` is for historical UtterPlan JSON schemas, not source files.

The compiled plan preserves SSMD header metadata, declared annotations, structural events, and effective typed directives. Audio and extension references are descriptive data only; consumers decide how to interpret them.
Structural text preserves the parsed document representation. Spoken text is
the prepared text and is the coordinate space used by segments, tokens,
markers, boundaries, and renderer-facing ranges.
