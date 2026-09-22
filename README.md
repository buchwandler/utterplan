[![PyPI - Version](https://img.shields.io/pypi/v/utterplan)](https://pypi.org/project/utterplan/)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/utterplan)
![PyPI - Downloads](https://img.shields.io/pypi/dm/utterplan)
[![codecov](https://codecov.io/gh/buchwandler/utterplan/graph/badge.svg?token=cL0qStxvDE)](https://codecov.io/gh/buchwandler/utterplan)

# UtterPlan

UtterPlan is an engine-independent TTS planning compiler and interchange
format. It converts text and SSMD into deterministic semantic speech plans
containing prepared spoken text, language runs, segments, pauses, directives,
markers, and render units. It stops before G2P and produces no audio.

## CLI

Compile literal text directly:

```bash
utterplan compile "Doctor Smith bought 5 kg." --lang en-us --json
```

Compile a file to a plan file:

```bash
utterplan compile chapter.ssmd --lang en-us -o chapter.utterplan.json
```

Use stdin and shell pipelines:

```bash
cat chapter.ssmd | utterplan compile --lang en-us --input-format ssmd | jq .
```

The CLI also provides:

```bash
utterplan --version
utterplan validate chapter.utterplan.json
utterplan inspect chapter.utterplan.json --segment 0
utterplan explain chapter.utterplan.json
```

`explain` presents the compiled plan as a human-readable speech plan, while `inspect` exposes lower-level diagnostic fields.
Compile JSON is written to stdout when no output file is supplied. Status
messages use stderr, and existing output files require `--force`.

## Planning defaults

The minimal CLI defaults are explicit: `spokenform` is the default text-preparation backend, `tts` is the default pause mode, and `spacy off` is the default linguistic-resource policy. With `spacy off`, UtterPlan uses its deterministic fallback tokenizer and analysis and does not depend on an installed spaCy model.

`spacy auto` is opt-in. When enabled and a compatible local model is available, UtterPlan may expose richer tokenization, POS tags, lemmas, and tags; `auto` is not the default.

## Python API

```python
from utterplan import PlannerConfig, UtterancePlan, UtterancePlanner

planner = UtterancePlanner(PlannerConfig(language="en-us"))
plan = planner.plan("Doctor Smith bought 5 kg of apples.")
plan.save("example.utterplan.json")
assert UtterancePlan.load("example.utterplan.json") == plan
```

The stable in-process boundary is `PlannerConfig`, `UtterancePlanner`, and the
immutable `UtterancePlan` object. JSON is the portable persistence and interchange
format; an in-process renderer can consume the Python object directly.

## Renderer-consumer boundary

Renderers consume `PlanSegment.text`, which is prepared/spoken text, and use
`spoken_start`/`spoken_end` for spoken-text coordinates. Resolved segment
pauses, language, directives, annotations, boundaries, markers, units, and
document metadata are public plan fields. Plans contain no phonemes, model
tokens, model sessions, renderer configuration, provider documents, or audio.

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
- [Changelog](docs/changelog.md)

## Versions

The package version is dynamically derived from Git tags by setuptools-scm. The
first public alpha package release is `0.1.0`. The package version and
UtterPlan `schema_version` is independent from the package version. Current plans use schema version `2`; schema v1 remains frozen and supported through a pure v1-to-v2 migration.

Schema v2 persists final pass-B token facts, including optional POS, tag, lemma, and morphology, plus per-language-run provider provenance. Unit hashes use `utterplan-unit-v2` and include pronunciation-relevant token semantics. Migration is representation conversion only and never reruns planning or linguistic analysis.

## Development

```bash
python -m pip install -e '.[dev,docs]'
python -m pytest -q
ruff check .
mypy utterplan
python -m build
sphinx-build -W --keep-going -b html docs docs/_build/html
```
