[![PyPI - Version](https://img.shields.io/pypi/v/utterplan)](https://pypi.org/project/utterplan/)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/utterplan)
![PyPI - Downloads](https://img.shields.io/pypi/dm/utterplan)
[![codecov](https://codecov.io/gh/buchwandler/utterplan/graph/badge.svg?token=cL0qStxvDE)](https://codecov.io/gh/buchwandler/utterplan)

# UtterPlan

UtterPlan is the canonical, engine-independent semantic compiler from one SSMD
document (or explicitly selected plain-text document) to an executable speech
plan. It produces deterministic prepared text, ordered flow units, segment-local
semantics, pause intents, portable document metadata, and typed directives for
independent consumers such as ttsready and Readio. It does not manage books or
consumer workspaces, and stops before G2P, synthesis, and audio.

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

This writes one `.utterplan.toml` per source plus an atomically refreshed `compile-report.toml`. Use `--fail-fast` to skip later inputs after a failure, `--force` to replace existing plans, or `--report PATH` to choose another report location.

The CLI also provides:

```bash
utterplan --version
utterplan validate chapter.utterplan.toml
utterplan inspect chapter.utterplan.toml --segment 0
utterplan inspect chapter.utterplan.toml --boundaries --tokens
utterplan explain chapter.utterplan.toml --trace chapter.trace.toml
utterplan inspect-trace chapter.trace.toml --preparation --boundaries
utterplan inspect-attempt chapter.attempt.toml --issues
```

`explain` presents executable flow as a human-readable speech plan. Use `compile --trace PATH` to retain optional compiler provenance; `explain --trace PATH` and `inspect-trace` read that sidecar separately from the plan.

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

`utterplan migrate` explicitly imports supported historical `.utterplan.json` plans and writes current TOML. It does not migrate SSMD source.
Normal plan loading is TOML-only: `FlowPlan.load()` and plan-inspection commands reject JSON rather than auto-detecting it.

## Planning defaults

The minimal CLI defaults are explicit: `spokenform` is the default text-preparation backend, `tts` is the default pause activation mode, and `spacy off` is the default linguistic-resource policy. With `spacy off`, UtterPlan uses its deterministic fallback tokenizer and analysis and does not depend on an installed spaCy model.

Python `PlannerConfig` defaults to `document_format="plain"`; set it to `"ssmd"` when a Python string contains SSMD source.

Python `PlannerConfig.renderability_mode` also defaults to safe punctuation-only repair; choose `"strict"` to reject every repair opportunity. Neither mode guesses a symbol's pronunciation or crosses semantic blockers.

`spacy auto` is opt-in. When enabled and a compatible local model is available, UtterPlan may expose richer tokenization, POS tags, lemmas, and tags; `auto` is not the default.

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

Renderers consume `FlowPlan.flow` in order. Each `FlowUnit` contains local `FlowSegment` objects with already-prepared speech text, effective language, segment-local token views, semantic pause intents, directives, markers, and optional heading level. Token `start`/`end` offsets are Python-character indexes into that segment's `text`; they are never document-global coordinates. Pause intents express `none`, semantic strengths, or exact authored times and do not prescribe engine-specific duration policy.

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
- [Format and schema](docs/format.md)
- [Consumer guide](docs/consumer-guide.md)
- [Architecture](docs/architecture.md)
- [Coordinates](docs/coordinate-spaces.md)
- [PyKokoro integration](docs/pykokoro-integration.md)
- [Python API](docs/python-api.md)
- [Debugging](docs/debugging.md)
- [Changelog](docs/changelog.md)

## Versions

The package version is dynamically derived from Git tags by setuptools-scm. Package version and UtterPlan schema version are independent. Current `.utterplan.toml` plans use semantic schema v5. Historical JSON Schemas v1–v4 remain immutable and supported through sequential migrations; v5 deliberately has no JSON Schema resource because its canonical executable contract is the validated TOML/FlowPlan model.

Schema v5 is a breaking redesign around ordered flow units and segment-local semantics. It preserves deterministic output and moves preparation/source provenance to an optional TOML trace sidecar, which does not affect plan identity. Migration converts serialized plan data only: v1–v4 migrate sequentially to v5 without reparsing, NLP, planning, G2P, rendering, or audio processing. The v4-to-v5 projection fails safely when historical token coordinates or pause semantics cannot be verified.

## Development

```bash
python -m pip install -e '.[dev,docs]'
python -m pytest -q
ruff check .
mypy utterplan
python -m build
sphinx-build -W --keep-going -b html docs docs/_build/html
```
