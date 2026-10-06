[![PyPI - Version](https://img.shields.io/pypi/v/utterplan)](https://pypi.org/project/utterplan/)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/utterplan)
![PyPI - Downloads](https://img.shields.io/pypi/dm/utterplan)
[![codecov](https://codecov.io/gh/buchwandler/utterplan/graph/badge.svg?token=cL0qStxvDE)](https://codecov.io/gh/buchwandler/utterplan)

# UtterPlan

UtterPlan is the canonical, engine-independent semantic compiler from one SSMD
document (or explicitly selected plain-text document) to an executable speech
plan. It produces deterministic language runs, prepared text, segments, resolved
pauses, portable metadata, directives, markers, and render units shared by
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

````bash
utterplan --version
utterplan validate chapter.utterplan.toml
utterplan inspect chapter.utterplan.toml --segment 0
utterplan inspect chapter.utterplan.toml --semantic-boundaries
utterplan explain chapter.utterplan.toml

`explain` presents the compiled plan as a human-readable speech plan, while `inspect` exposes lower-level diagnostic fields.
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
````

`utterplan migrate` explicitly imports supported historical `.utterplan.json` plans and writes current TOML. It does not migrate SSMD source.
Normal plan loading is TOML-only: `UtterancePlan.load()` and plan-inspection commands reject JSON rather than auto-detecting it.

## Planning defaults

The minimal CLI defaults are explicit: `spokenform` is the default text-preparation backend, `tts` is the default pause mode, and `spacy off` is the default linguistic-resource policy. With `spacy off`, UtterPlan uses its deterministic fallback tokenizer and analysis and does not depend on an installed spaCy model.

Python `PlannerConfig` defaults to `document_format="plain"`; set it to `"ssmd"` when a Python string contains SSMD source.

Python `PlannerConfig.renderability_mode` also defaults to safe punctuation-only repair; choose `"strict"` to reject every repair opportunity. Neither mode guesses a symbol's pronunciation or crosses semantic blockers.

`spacy auto` is opt-in. When enabled and a compatible local model is available, UtterPlan may expose richer tokenization, POS tags, lemmas, and tags; `auto` is not the default.

## Python API

```python
from utterplan import PlannerConfig, UtterancePlan, compile_document

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
assert UtterancePlan.load("example.utterplan.toml") == plan
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

Renderers consume `PlanSegment.text`, which is prepared/spoken text, and use
`spoken_start`/`spoken_end` for spoken-text coordinates. Resolved segment
pauses, language, directives, annotations, boundaries, semantic boundaries,
markers, units, and
document metadata are public plan fields. Semantic boundaries are stable
engine-neutral opportunities for spoken-text subdivision; they are not pause
events and carry no duration or renderer policy. Plans contain no phonemes, model
tokens, model sessions, renderer configuration, provider documents, or audio.
For SSMD input, `plan.annotations` preserve declared source semantics and source
provenance, `document_metadata` preserves portable header data, and
`segment.directives` carries effective typed semantics after scope and voice-default
resolution. Typed directives include voice, pronunciation, prosody, emphasis, say-as,
substitution, audio references, and extension references. Audio and extensions are
data only. UtterPlan does not fetch media or execute extension handlers.

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

The package version is dynamically derived from Git tags by setuptools-scm. Package version and UtterPlan schema version are independent. Current `.utterplan.toml` plans use semantic schema v4; released schema v1, v2, and v3 remain immutable and supported through sequential migrations.

Schema v4 adds stable `SemanticBoundary` records in spoken-text coordinates. Migration converts serialized plan data only: the registered v3-to-v4 step preserves existing evidence and derives topology where possible, but does not rerun parsing, NLP, planning, G2P, rendering, or audio processing. Unit hashes use `utterplan-unit-v3` and include relative semantic-boundary positions; older hash algorithms remain available for their historical migration paths.
Schema v4 retains typed renderer-neutral SSMD semantics, final pass-B token facts, and per-language-run provider provenance. Plans never serialize provider documents, models, sessions, phonemes, token IDs, or audio.

## Development

```bash
python -m pip install -e '.[dev,docs]'
python -m pytest -q
ruff check .
mypy utterplan
python -m build
sphinx-build -W --keep-going -b html docs docs/_build/html
```
