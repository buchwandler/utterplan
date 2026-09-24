# UtterPlan 0.3.0 Release / Breaking-Change Audit

**Audit date:** 2026-09-24
**Target:** `utterplan` 0.3.0
**Primary compatibility target:** SSMD 0.9 only
**Reviewed repositories:** `utterplan`, `ssmd`, `phrasplit`
**Additional dependency snapshot inspected for test interpretation:** `spokenform`

## Executive verdict

**Do not publish the exact audited snapshot as UtterPlan 0.3.0 yet.**

The SSMD 0.9 migration is substantially implemented and the core direction is correct:

- `utterplan` already pins `ssmd>=0.9.0,<0.10`.
- SSMD parsing explicitly selects `dialect="0.9"`.
- Explicit 0.8 version headers are rejected.
- Strict 0.9 syntax diagnostics are propagated with stable codes.
- Portable 0.9 front matter is preserved.
- `.ssmd.md`, `.ssmd`, and versioned `.md` CLI inference matches the new SSMD conventions.
- Source provenance, headings, voice data, language tags, paragraph structure, breaks, marks, annotations, and extension data are represented without requiring renderer-specific behavior.
- The focused SSMD/directive/language test set passes when the reconstructed dependency snapshots are placed on `PYTHONPATH`.

However, there are **three concrete release blockers** in the audited source, plus a required release-gate step:

1. **SSMD explicit-break precedence is wrong.** At a boundary shared by an explicit SSMD break and an automatically generated/default pause, `utterplan` currently selects the longest duration. SSMD 0.9 requires an explicit source break to take precedence over `pause_defaults`.
2. **CI and publish validation still contain SSMD 0.8.7.** The lower-bound test job installs `ssmd==0.8.7`, and the publish artifact validator only requires an SSMD minimum of 0.8.7. Both contradict the package dependency and the intended 0.9-only contract.
3. **`utterplan/py.typed` is declared and required but missing.** The wheel builds, but the built wheel does not contain `utterplan/py.typed`; the repository's own package-smoke job explicitly requires it.
4. **The release must be completed through the normal release ledger and a clean CI run against installed/published dependencies.** The generated changelog still has an empty `Unreleased` section and no 0.3.0 release entry.

After those are corrected, **0.3.0 is a good boundary for a small set of intentional breaking API cleanups**. Do not use it as an excuse for wholesale churn.

> SemVer terminology: `0.3.0` is not a numeric SemVer major version. It is a pre-1.0 minor release. For a project still marked Alpha, it is nevertheless a reasonable boundary for documented breaking changes.

---

# 1. Scope and reconstruction

The Codecrate packs were reconstructed with their generated standalone unpackers using strict checksum/warning validation.

Conceptually, the commands were:

```bash
python3 -S context_utterplan.unpack.py context_utterplan.md \
  -o reconstructed/utterplan \
  --check-machine-header --strict --fail-on-warning

python3 -S context_ssmd.unpack.py context_ssmd.md \
  -o reconstructed/ssmd \
  --check-machine-header --strict --fail-on-warning

python3 -S context_phrasplit.unpack.py context_phrasplit.md \
  -o reconstructed/phrasplit \
  --check-machine-header --strict --fail-on-warning
```

All three reconstructed cleanly.

The analysis below treats the reconstructed source as authoritative for code review. Current package availability was separately checked against PyPI because the SSMD release ledger snapshot can lag the package registry.

---

# 2. Current dependency contract

`pyproject.toml` already has the correct intended runtime pins:

```toml
dependencies = [
  "phrasplit>=0.3.9,<0.4",
  "ssmd>=0.9.0,<0.10",
  "spokenform>=0.4.3,<0.5",
  "typing_extensions>=4.0",
]
```

Relevant location:

- `pyproject.toml:14-18`

This is the right dependency direction for 0.3.0.

At audit time, the required public dependencies exist:

- SSMD 0.9.0 is published.
- phrasplit 0.3.9 is published.

Therefore dependency sequencing is **not** a release blocker. The remaining 0.8.7 references are stale UtterPlan workflow configuration, not a need to wait for SSMD.

---

# 3. SSMD 0.9 support review

## 3.1 Dialect selection: ready

`SSMDDocumentParser` explicitly requests SSMD 0.9:

```python
parsed = ssmd.parse_structure(
    text,
    default_lang=None,
    parse_yaml_header=config.ssmd.parse_header,
    resolve_defaults=False,
    dialect="0.9",
)
```

Location:

- `utterplan/parsers.py:46-71`

This is important because it makes unversioned SSMD fragments use the 0.9 grammar rather than silently accepting legacy syntax.

Existing test:

- `tests/test_ssmd_09_parser.py::test_ssmd_09_parser_uses_strict_dialect_for_unversioned_fragments`

It verifies that a legacy comma separator is rejected with:

```text
syntax.comma_separator_legacy
```

### Decision

Keep this explicit `dialect="0.9"` call. Do not add 0.8 fallback logic.

---

## 3.2 Explicit SSMD 0.8 documents: ready

Existing test data verifies:

```yaml
---
ssmd_version: "0.8"
---
Hello.
```

is rejected with:

```text
header.version_unsupported
```

Locations:

- `tests/test_ssmd_09_parser.py:35-60`

### Decision

This is exactly the desired behavior for UtterPlan 0.3.0.

Do **not** implement source migration in UtterPlan. Keep the existing division of responsibility:

```text
old SSMD source -> ssmd migrate ... --to 0.9 -> utterplan compile
```

UtterPlan plan-schema migration and SSMD source migration are different operations.

---

## 3.3 Portable SSMD 0.9 front matter: ready

The parser preserves these portable keys:

```python
(
    "ssmd_version",
    "title",
    "language",
    "voice_bindings",
    "voice_defaults",
    "pause_defaults",
    "prosody_transitions",
    "language_detection",
    "requires",
)
```

Location:

- `utterplan/parsers.py:153-167`

The comprehensive test covers language, voice bindings/defaults, pause defaults, prosody transitions, language detection, and extension requirements.

Relevant test:

- `tests/test_ssmd_09_parser.py::test_ssmd_front_matter_is_preserved_and_sets_document_language`

### Decision

Keep document metadata portable and renderer-independent.

UtterPlan should **preserve** fields such as `voice_bindings`, `prosody_transitions`, and `language_detection`; it should not attempt to become the provider-specific SSMD renderer.

---

## 3.4 BCP-47 language preservation: ready

The SSMD path sets:

```python
preserve_language_tags = config.document_format == "ssmd"
```

and the tests explicitly verify authored values such as:

```text
sr-Latn
en-GB
```

remain authored values in plan runs/segments while lookup keys can normalize separately.

Relevant test:

- `tests/test_ssmd_09_parser.py::test_authored_language_tags_are_preserved_while_lookup_keys_normalize`

### Decision

Keep this separation:

- **serialized/authored identity:** original BCP-47 spelling
- **lookup identity:** normalized internal key

Do not normalize away authored region/script information.

---

## 3.5 Structural/source provenance: ready

SSMD annotations are mapped with original-source provenance:

- `source_start`
- `source_end`
- `source_node_id`

The schema-v3 round-trip test already verifies that source provenance survives serialization.

Relevant test:

- `tests/test_ssmd_09_parser.py::test_ssmd_annotation_source_provenance_roundtrips_in_schema_v3`

### Decision

This is a strong part of the current design. Keep it.

---

## 3.6 Heading semantics: ready

SSMD heading events are retained as structural events but marked:

```python
"structural_only": True
```

and therefore do not create synthesized pauses.

Relevant locations:

- `utterplan/parsers.py:141-150`
- `tests/test_ssmd_09_parser.py::test_heading_events_are_preserved_but_inactive_for_pause_resolution`

### Decision

Keep the current behavior.

---

## 3.7 Filename / CLI inference: ready

Existing tests cover:

```text
chapter.ssmd       -> ssmd
chapter.ssmd.md    -> ssmd
chapter.md with ssmd_version -> ssmd
ordinary.md        -> plain
```

Relevant tests:

- `tests/test_ssmd_09_parser.py::test_cli_auto_detection_recognizes_ssmd_names_and_versioned_markdown`
- `tests/test_ssmd_09_parser.py::test_cli_compiles_versioned_markdown_as_ssmd`
- `tests/test_ssmd_09_parser.py::test_cli_auto_detection_keeps_ordinary_markdown_plain`

This matches SSMD 0.9's revised convention that `.ssmd.md` is recommended, `.ssmd` remains supported, and ordinary `.md` is generic Markdown unless explicitly versioned.

### Decision

No change required here.

---

## 3.8 Paragraph semantics around fenced voice scopes: ready

SSMD 0.9 specifically changed paragraph preservation around adjacent fenced voice scopes.

The current SSMD parser snapshot produces the expected structural distinctions, and UtterPlan consumes SSMD paragraph events rather than independently guessing paragraph structure from the markup.

### Decision

No compatibility shim is needed in UtterPlan. Keep paragraph ownership in SSMD.

---

## 3.9 Audio semantics: no blocker found

SSMD 0.9 distinguishes:

- annotation content as spoken fallback
- `desc` as description metadata
- legacy `alt` as compatibility syntax

The current UtterPlan direction is compatible with that separation. A legacy `alt_text` field still exists in the plan model for historical plan compatibility, but the strict 0.9 source path does not need to populate it from new source.

### Decision

Do not remove historical `AudioDirective.alt_text` merely because SSMD 0.9 changed source authoring. Removing a field from historical plan decoding would create a separate UtterPlan schema compatibility problem.

---

# 4. P0 release blocker: explicit SSMD breaks lose precedence

This is the most important semantic issue found.

SSMD 0.9 specifies:

> Explicit break markers in the SSMD body take precedence over `pause_defaults`. When several default pause types apply at the same boundary, use the longest applicable default rather than adding them.

UtterPlan currently resolves all boundary events at a position using one `max()`:

```python
def _pause(events: list[BoundaryEvent]) -> ResolvedPause:
    if not events:
        return ResolvedPause()
    winner = max(events, key=lambda event: (float(event.seconds or 0), event.id))
    return ResolvedPause(...)
```

Location:

- `utterplan/pauses.py:61+`

The existing test explicitly locks in the conflicting behavior:

```python
BoundaryEvent(
    "sentence",
    5,
    "sentence",
    seconds=0.6,
    ...
),
BoundaryEvent(
    "break",
    5,
    "explicit",
    seconds=0.2,
    origin="ssmd",
    ...
),
...
assert resolved.pause_after.seconds == pytest.approx(0.6)
```

Location:

- `tests/test_pauses.py:~156-178`

That test passes today, proving the current behavior is intentional but incompatible with the SSMD 0.9 precedence rule.

## Required implementation

Resolve precedence before duration comparison.

Recommended rule:

1. Preserve **all** contributing event IDs for provenance.
2. If one or more explicit SSMD source-break events exist at a boundary, select among those explicit events only.
3. If no explicit source break exists, select the longest applicable automatic/default event.
4. Never add durations together.

A minimal shape:

```python
def _pause(events: list[BoundaryEvent]) -> ResolvedPause:
    if not events:
        return ResolvedPause()

    explicit = [
        event
        for event in events
        if event.origin == "ssmd"
        and event.kind == "explicit"
        and event.attrs.get("pause_origin") == "explicit"
    ]
    candidates = explicit or events
    winner = max(candidates, key=lambda event: (float(event.seconds or 0.0), event.id))

    return ResolvedPause(
        seconds=float(winner.seconds or 0.0),
        events=tuple(sorted(event.id for event in events)),
    )
```

The exact explicit predicate can be adjusted, but it must distinguish an authored source break from a break whose duration itself came from defaults.

## Tests to add/change

Change the existing overlapping-source test to expect:

```python
assert resolved.pause_after.seconds == pytest.approx(0.2)
assert resolved.pause_after.events == ("break", "sentence")
```

Also add integration cases:

### Explicit timed break beats sentence default

```ssmd
---
ssmd_version: "0.9"
pause_defaults:
  sentence: 800ms
---

One. ...200ms Two.
```

Expected boundary duration at the explicit break:

```text
0.2 seconds
```

not 0.8.

### Longest default still wins when no explicit source break exists

At a boundary where sentence and paragraph defaults coincide, use the longer default and retain both event IDs.

### Zero-duration explicit break

An authored explicit `0ms` break must still beat a generated/default pause if SSMD permits that exact source representation. This catches implementations that use truthiness instead of explicit provenance.

---

# 5. P0 release blocker: CI still installs SSMD 0.8.7

`pyproject.toml` is correct, but `.github/workflows/tests.yml` is stale.

Current lower-bound job:

```yaml
python -m pip install \
"phrasplit==0.3.9" \
"ssmd==0.8.7" \
"spokenform==0.4.3" \
"typing_extensions>=4.0"
```

Location:

- `.github/workflows/tests.yml:43-54`

## Required change

```diff
- "ssmd==0.8.7" \
+ "ssmd==0.9.0" \
```

This should be treated as a hard release blocker because a lower-bound job using 0.8.7 no longer tests a supported environment.

---

# 6. P0 release blocker: publish validation still accepts SSMD 0.8.7

Current artifact validation:

```python
assert has_minimum(requirements, "phrasplit", "0.3.9")
assert has_minimum(requirements, "ssmd", "0.8.7")
assert has_minimum(requirements, "spokenform", "0.4.3")
```

Location:

- `.github/workflows/python-publish.yml:76-83`

## Required change

```diff
- assert has_minimum(requirements, "ssmd", "0.8.7")
+ assert has_minimum(requirements, "ssmd", "0.9.0")
```

## Recommended strengthening

The current helper checks only the lower bound. The release contract is actually:

```text
ssmd >= 0.9.0, < 0.10
phrasplit >= 0.3.9, < 0.4
spokenform >= 0.4.3, < 0.5
```

If the publish workflow is intended to protect metadata, validate the upper bounds too. This prevents an accidental future edit such as `ssmd>=0.9.0` from silently dropping the compatibility ceiling.

---

# 7. P0 packaging blocker: `py.typed` is missing

`pyproject.toml` says the package is typed:

```toml
classifiers = [
  ...
  "Typing :: Typed",
]
```

and declares:

```toml
[tool.setuptools.package-data]
utterplan = ["py.typed", "utterplan.schema.json", "schemas/*.schema.json"]
```

Locations:

- `pyproject.toml:20-31`
- `pyproject.toml:47-48`

The repository workflow also requires:

```python
assert "utterplan/py.typed" in names
```

Location:

- `.github/workflows/tests.yml:68-80`

But the audited package directory contains no:

```text
utterplan/py.typed
```

A wheel build succeeds, and the resulting wheel contains:

```text
utterplan/utterplan.schema.json
utterplan/schemas/v1.schema.json
utterplan/schemas/v2.schema.json
utterplan/schemas/v3.schema.json
```

but **does not contain `utterplan/py.typed`**.

## Required fix

Add an empty PEP 561 marker:

```text
utterplan/py.typed
```

Then verify both wheel and sdist.

Do not remove the `Typing :: Typed` classifier to make the test pass; the package exposes typed public APIs and should ship the marker.

---

# 8. Release metadata / release-process gate

`docs/changelog.md` currently begins:

```markdown
## [Unreleased]

## [0.2.0] - 2026-09-22
```

Location:

- `docs/changelog.md:1-7`

The current source contains material 0.3 changes, including schema v3 and SSMD 0.9 support, but the generated changelog has not yet been populated for a 0.3.0 release.

## Required before tagging

Use releaseledger rather than manually editing generated output.

The 0.3.0 release record should clearly include:

### Changed

- Require SSMD `>=0.9.0,<0.10`.
- Parse SSMD exclusively with strict 0.9 semantics.
- Adopt SSMD 0.9 front matter, filename inference, source provenance, and paragraph behavior.
- Correct explicit-break precedence.
- Any intentional Python API/config break selected from section 10.

### Removed

- SSMD 0.8 source compatibility.
- No-op SSMD config options if accepted below.
- Compatibility aliases only if the optional aggressive cleanup is accepted.

### Migration

- Old **SSMD source**: run `ssmd migrate FILE --to 0.9`.
- Old **UtterPlan JSON plan**: continue using UtterPlan plan migration. Do not reparse/replan.

---

# 9. Important distinction: do not drop old UtterPlan plan schemas

SSMD source compatibility and UtterPlan serialized-plan compatibility are separate contracts.

Current versioning:

```python
FORMAT = "utterplan"
CURRENT_SCHEMA_VERSION = 3
OLDEST_SUPPORTED_SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = (1, 2, 3)
```

Location:

- `utterplan/versioning.py`

The repository has:

```text
v1 -> v2 -> v3
v2 -> v3
```

migrations and immutable historical schema fixtures.

## Recommendation

**Keep plan-schema v1 and v2 migration support in UtterPlan 0.3.0.**

Dropping SSMD 0.8 source parsing does **not** justify dropping already serialized UtterPlan plans.

This also keeps the architecture clean:

```text
source-dialect migration != compiled-plan migration
```

Do not introduce schema v4 merely because the Python API changes. Create schema v4 only if the serialized UtterPlan contract itself needs a meaningful incompatible change.

---

# 10. Recommended intentional breaking changes for 0.3.0

The following are worth doing before the new public surface settles.

## 10.1 Change Python default `document_format` from `ssmd` to `plain`

Current:

```python
@dataclass(...)
class PlannerConfig:
    language: str
    document_format: Literal["plain", "ssmd"] = "ssmd"
```

Location:

- `utterplan/config.py:113-124`

This is surprising for a general text-to-speech planning compiler.

The CLI already behaves more safely:

- ordinary Markdown stays plain
- literal/plain input is not automatically treated as authored SSMD
- recognized SSMD filenames/front matter opt into SSMD

The Python default should follow the same principle.

### Proposed 0.3 behavior

```python
PlannerConfig(
    language="en-us",
    document_format="plain",
)
```

by default.

SSMD callers use:

```python
PlannerConfig(
    language="en-us",
    document_format="ssmd",
)
```

### Why this is worth breaking now

A plain string can contain brackets, braces, headings, or punctuation that resembles markup. Treating every Python string as SSMD by default makes accidental semantics possible.

For a dependency such as PyKokoro, plain text should be the safe default.

### Migration note

Before:

```python
UtterancePlanner(PlannerConfig(language="en-us")).plan(ssmd_text)
```

After:

```python
UtterancePlanner(
    PlannerConfig(language="en-us", document_format="ssmd")
).plan(ssmd_text)
```

Plain-text callers usually require no change.

---

## 10.2 Remove the no-op `SSMDConfig.strict_header`

Current:

```python
class SSMDConfig:
    parse_header: bool = True
    strict_header: bool = True
    unknown_header: Literal["warn", "error", "ignore"] = "warn"
    ...
```

Location:

- `utterplan/config.py:89-110`

`strict_header` is validated and serialized, but the parser does not read it.

SSMD 0.9 owns header validation.

### Recommendation

Remove `strict_header` in 0.3.0.

Do not keep public switches that imply behavior but have no effect.

---

## 10.3 Remove the no-op `SSMDConfig.unknown_header`

`unknown_header` is also validated and serialized but not passed into SSMD or otherwise applied.

The actual current behavior comes from SSMD's structured parser diagnostics. For example, the existing test for an unknown header key asserts the SSMD parser's:

```text
header.unknown_key
```

warning.

Relevant test:

- `tests/test_consumer_readiness.py::test_ssmd_unknown_header_uses_parser_diagnostic`

### Recommendation

Remove `unknown_header`.

If application-level diagnostic policy is wanted later, implement one generic diagnostic policy at UtterPlan level rather than an SSMD-specific option that pretends to control the parser.

---

## 10.4 Keep the header-disable capability, but rename it if API cleanup is desired

Unlike the two fields above, `parse_header` is real and tested.

It is passed to:

```python
ssmd.parse_structure(..., parse_yaml_header=...)
```

and this test verifies it:

- `tests/test_consumer_readiness.py::test_ssmd_parse_header_false_does_not_consume_front_matter`

Therefore do **not** remove it merely because 0.8 support is removed.

If 0.3 is already breaking the config, a clearer name would be:

```text
parse_yaml_header
```

to match SSMD's actual API.

Possible migration:

```diff
- SSMDConfig(parse_header=False)
+ SSMDConfig(parse_yaml_header=False)
```

This rename is optional. It is clarity cleanup, not a correctness fix.

---

## 10.5 Rename `SSMDConfig.pause_defaults` to reflect that it is an override

Current precedence in `_effective_pause_config()` is:

```text
PlannerConfig.pauses
    then SSMD header pause_defaults
        then config.ssmd.pause_defaults
```

So the field named:

```text
SSMDConfig.pause_defaults
```

is not really a default. It is an application-level override of document defaults.

Locations:

- `utterplan/config.py:89-110`
- `utterplan/planner.py:157-190`
- `utterplan/parsers.py:235-298`

### Recommended 0.3 API

Rename it to:

```text
SSMDConfig.pause_overrides
```

and document precedence explicitly:

```text
explicit source break
    >
application SSMD pause override
    >
document pause_defaults
    >
planner PauseConfig defaults
```

The exact position of application override vs document defaults is a policy choice, but the current behavior already puts application config above the document. If retaining that behavior, name it honestly.

### Important

This is separate from the P0 explicit-break bug. Even if application defaults override document defaults, **an authored explicit source break must still win at its boundary**.

---

# 11. phrasplit 0.3.9 integration review

UtterPlan correctly pins:

```text
phrasplit>=0.3.9,<0.4
```

There is, however, a missed integration opportunity.

## 11.1 Keep deterministic sentence topology

Current sentence splitting deliberately uses:

```python
phrasplit.split_with_offsets(
    text,
    mode="sentence",
    use_spacy=False,
    ...
)
```

Locations:

- `utterplan/planner.py:297-333`
- `utterplan/stages/segmentation/phrasplit.py:8-33`

The comment in `_split_run()` is sound:

```python
# Linguistic enrichment is consumed for token annotations only.
# Sentence topology stays on the deterministic phrasplit path.
```

### Recommendation

Keep this.

Do not make plan sentence topology depend on whether a machine happens to have a spaCy model installed.

---

## 11.2 Fix clausal-comma enrichment to use the already-owned spaCy document

Current linguistic boundary code does:

```python
clause_items = phrasplit.detect_clause_boundaries(
    local,
    language=...,
    use_spacy=False,
)
```

Location:

- `utterplan/planner.py:407-473`

But phrasplit 0.3.9 explicitly documents:

```text
Detection requires spaCy-like dependency, subject, and finite-predicate annotations;
regex mode never guesses.
```

Its implementation returns an empty list when a spaCy backend/document is not active.

Therefore this UtterPlan call effectively disables syntactic clausal-comma detection.

At the same time, UtterPlan already performs linguistic analysis and keeps a request-local:

```python
RunAnalysis.provider_doc
```

when spaCy is used.

Locations:

- `utterplan/linguistics.py:13-25`
- `utterplan/linguistics.py:89-129`
- `utterplan/linguistics.py:163-201`

phrasplit 0.3.9 accepts a caller-owned:

```python
doc=...
```

for `detect_clause_boundaries()`.

### Recommended implementation

Change `_linguistic_boundaries` to accept the matching `pass_b` analyses:

```python
boundaries.extend(
    _linguistic_boundaries(
        spoken,
        runs,
        pass_b,
        config,
        start_id=len(boundaries),
    )
)
```

Then:

```python
for run, analysis in zip(runs, analyses, strict=True):
    local = text[run.spoken_start:run.spoken_end]
    doc = analysis.provider_doc if analysis.provider == "spacy" else None

    clause_items = phrasplit.detect_clause_boundaries(
        local,
        language=language_lookup_key(run.language),
        use_spacy=True if doc is not None else False,
        doc=doc,
    )
```

Better still, if phrasplit accepts `doc` as sufficient backend selection, avoid redundantly forcing `use_spacy=True`.

### Required invariant

**Do not run spaCy a second time.**

UtterPlan already owns the analyzed request-local doc. Reuse it.

### Tests

Add a test with a fake spaCy-like analyzed document or existing phrasplit test fixture:

- provider doc supplied -> clausal-comma boundary appears
- fallback analysis -> no guessed clausal comma
- sentence segmentation remains identical in both cases

---

## 11.3 Remove the unused `_split_run(..., analysis=...)` parameter

Current signature:

```python
def _split_run(
    text: str,
    language: str,
    config: PlannerConfig,
    analysis: Any | None = None,
) -> list[Any]:
```

but `analysis` is unused.

Location:

- `utterplan/planner.py:297-333`

### Recommendation

Remove the argument unless the implementation is deliberately changed to consume it.

Unused API surface inside core planning code makes it unclear whether segmentation is supposed to depend on linguistic analysis.

---

## 11.4 Consolidate the duplicate phrasplit stage wrapper

There are currently two sentence-splitting paths:

- `_split_run()` in `utterplan/planner.py`
- `split_text()` in `utterplan/stages/segmentation/phrasplit.py`

Repository search found no consumer of the `stages/segmentation/phrasplit.py` wrapper outside that module.

### Recommendation

Before 0.3.0, choose one architecture:

**Preferred:** keep the actual segmentation implementation in a stage module and make the planner call it.

or, if the staged architecture is not being used:

**Alternative:** remove the dead stage wrappers until a real pluggable stage architecture exists.

Do not maintain duplicate integrations with different fallback/error behavior.

This is an internal cleanup and should not force a plan-schema change.

---

# 12. Compatibility aliases: optional aggressive cleanup

The model still exposes several Python compatibility aliases:

```text
AnnotationSpan.char_start -> structural_start
AnnotationSpan.char_end   -> structural_end

TokenAnnotation.start -> spoken_start
TokenAnnotation.end   -> spoken_end

BoundaryEvent.pos        -> position
BoundaryEvent.duration_s -> seconds

ResolvedPause.duration_s -> seconds

PlanSegment.char_start     -> spoken_start
PlanSegment.char_end       -> spoken_end
PlanSegment.paragraph_idx  -> paragraph
PlanSegment.sentence_idx   -> sentence
PlanSegment.clause_idx     -> clause
```

Locations:

- `utterplan/model.py`

These aliases are mostly not used by the current docs/tests except as explicit compatibility surface.

## Recommendation

This is **optional**, not a release requirement.

If 0.3.0 is intended to be the final broad cleanup before downstream adoption expands, removing these aliases would make the coordinate-space vocabulary much clearer.

The strongest names are the current canonical ones:

```text
source_*
structural_*
spoken_*
position
seconds
paragraph / sentence / clause
```

### Only remove them if

- downstream consumers are under your control or can migrate now;
- a migration section lists every rename;
- no serialized JSON key is changed accidentally.

Removing Python properties alone does not require dropping historical plan schemas.

If consumers already use these aliases in the wild, keep them until 1.0 and deprecate them instead.

---

# 13. What I would NOT break in 0.3.0

## 13.1 Do not drop schema v1/v2 plan migrations

Covered above. Source dialect migration is not compiled-plan migration.

## 13.2 Do not make sentence segmentation spaCy-dependent

The deterministic regex-backed sentence topology is a good property for reproducible plans.

Use spaCy for enrichment where available, not for changing fundamental topology implicitly.

## 13.3 Do not move provider-specific rendering into UtterPlan

SSMD 0.9 contains provider target/capability work, but UtterPlan is correctly engine-independent.

Preserve semantic data. Let renderers consume it.

## 13.4 Do not resolve voice bindings to provider voice IDs inside the core plan

Keep logical voice identity and portable metadata. Provider resolution belongs downstream.

## 13.5 Do not execute/fetch SSMD extensions

Preserve trusted extension data as typed semantics. UtterPlan should not become an extension execution host.

## 13.6 Do not create schema v4 solely for Python API cleanup

Schema v3 is already the current serialized contract and supports source provenance.

Only create v4 if the JSON representation itself needs a genuinely incompatible semantic change.

## 13.7 Do not remove the SSMD migration guidance

Even though UtterPlan itself becomes 0.9-only, docs should keep the one-line migration route:

```bash
ssmd migrate FILE --to 0.9
```

That is the correct transition path for users with old source files.

---

# 14. Test and build findings

## 14.1 Reconstruction

Result:

```text
PASS
```

for strict Codecrate reconstruction of:

- utterplan
- ssmd
- phrasplit

## 14.2 Python compilation

Command:

```bash
python -m compileall -q utterplan
```

Result:

```text
PASS
```

## 14.3 Focused SSMD/API tests

With the reconstructed `ssmd` and `phrasplit` checkouts on `PYTHONPATH`:

```bash
python -m pytest -q \
  tests/test_ssmd_09_parser.py \
  tests/test_directives.py \
  tests/test_language.py
```

Result:

```text
33 passed
```

This is useful evidence that the new parser/directive surface is in good shape.

## 14.4 Full test suite in this audit environment

A full run produced:

```text
106 passed
72 failed
```

Do **not** interpret the raw failure count as 72 UtterPlan regressions.

Most failures come from the reconstructed `spokenform` checkout importing a transitive package (`abbr2words`) that is not present in this audit environment.

Additional environment/snapshot-specific failures include:

- unpacked source has no Git metadata, so `setuptools-scm` reports fallback version `0.0.0`; tests expecting the released project version fail;
- the analysis Python process already has `numpy` loaded, so the import-boundary test is contaminated by the host environment;
- `utterplan/py.typed` is genuinely missing and is a real source/package failure.

### Release rule

The actual 0.3.0 release gate must be a **clean GitHub CI run using installed published dependencies**, not the dependency-incomplete Codecrate analysis runtime.

## 14.5 Wheel build

A no-dependency wheel build succeeds.

Observed contents include:

```text
utterplan/utterplan.schema.json
utterplan/schemas/v1.schema.json
utterplan/schemas/v2.schema.json
utterplan/schemas/v3.schema.json
```

Observed missing resource:

```text
utterplan/py.typed
```

The wheel version in this unpacked audit tree is `0.0.0`; that is expected from missing VCS/tag metadata and is not itself a repository defect.

## 14.6 Static checks

`ruff`, `mypy`, and Sphinx are not installed in the current audit runtime, so no claim is made that those checks are green.

They must run in normal project CI before release.

---

# 15. Strengthen the release test matrix

The existing workflow is already reasonably broad, but 0.3.0 should add explicit contract tests for the new boundary.

## 15.1 Add an SSMD 0.9-only installed-wheel smoke test

After installing the built wheel, compile a strict 0.9 document:

```bash
cat > "$RUNNER_TEMP/test.ssmd.md" <<'EOF'
---
ssmd_version: "0.9"
language: en-US
pause_defaults:
  sentence: 500ms
---
[Hello]{voice-name="test"} ...200ms world.
EOF

utterplan compile "$RUNNER_TEMP/test.ssmd.md" \
  --lang en-us \
  --text-preparation identity \
  --json > "$RUNNER_TEMP/test.utterplan.json"

utterplan validate "$RUNNER_TEMP/test.utterplan.json"
```

Then verify an explicit 0.8 document fails.

This ensures the **installed wheel**, not just the source checkout, actually enforces the new source contract.

## 15.2 Verify every packaged schema resource

Current package-smoke checks only v1 plus the current alias.

Change it to assert:

```text
utterplan/utterplan.schema.json
utterplan/schemas/v1.schema.json
utterplan/schemas/v2.schema.json
utterplan/schemas/v3.schema.json
utterplan/py.typed
```

## 15.3 Add docs build to release gate

There is no obvious docs build in the inspected test workflow.

Recommended release check:

```bash
python -m sphinx -W --keep-going -b html docs docs/_build/html
```

Using `-W` is especially useful after changing public configuration names and migration documentation.

---

# 16. Concrete coding-agent implementation plan

## Phase 1 — Correct release blockers

### 1. Add PEP 561 marker

Create:

```text
utterplan/py.typed
```

empty file.

Update/retain package smoke tests.

### 2. Remove stale 0.8 CI references

Edit:

```text
.github/workflows/tests.yml
.github/workflows/python-publish.yml
```

Change all UtterPlan support expectations from:

```text
md 0.8.7
```

to:

```text
ssmd 0.9.0
```

Search repository-wide afterward:

```bash
rg '0\.8|0.8.7|ssmd==0\.8'
```

Any remaining 0.8 mention must be one of:

- migration documentation;
- a negative test that verifies rejection;
- historical release data.

There should be no 0.8 compatibility path or supported dependency declaration.

### 3. Fix pause precedence

Edit:

```text
utterplan/pauses.py
tests/test_pauses.py
```

Add integration coverage in one of:

```text
tests/test_ssmd_09_parser.py
tests/test_pauses.py
```

Acceptance:

```text
explicit SSMD source break > defaults/automatic pause at same boundary
```

while retaining all contributing event IDs.

---

## Phase 2 — Make the selected 0.3 API breaks

### 4. Change plain text to the Python default

Edit:

```text
utterplan/config.py
README.md
docs/getting-started.md
docs/python-api.md
docs/consumer-guide.md
examples/*
tests/*
goldens as needed
```

Change:

```python
document_format="ssmd"
```

default to:

```python
document_format="plain"
```

Every SSMD-specific test/example should opt in explicitly.

### 5. Remove dead header options

Remove:

```text
SSMDConfig.strict_header
SSMDConfig.unknown_header
```

Update serialized config goldens.

Do **not** add replacements unless real behavior is implemented.

### 6. Optional naming cleanup

If accepted, rename:

```text
parse_header -> parse_yaml_header
pause_defaults -> pause_overrides
```

Update:

```text
utterplan/config.py
utterplan/parsers.py
utterplan/planner.py
docs/*
tests/*
goldens
```

Document precedence.

---

## Phase 3 — Use phrasplit 0.3.9 properly

### 7. Reuse linguistic provider docs for clausal boundaries

Pass `pass_b` into `_linguistic_boundaries()`.

For each language run:

- if analysis provider is spaCy and `provider_doc` exists, pass it to phrasplit;
- otherwise do not guess syntactic clause boundaries.

Do not run a second NLP pipeline.

### 8. Keep deterministic sentence segmentation

Retain `use_spacy=False` for sentence topology unless a future explicit config introduces a reproducibility-breaking mode.

### 9. Remove unused `_split_run` analysis argument

Or make it genuinely participate in a documented deterministic algorithm.

### 10. Consolidate duplicate phrasplit wrapper code

Pick one integration implementation and one error/fallback policy.

---

## Phase 4 — Optional Python surface cleanup

### 11. Decide on compatibility property aliases

If removing them, do so in one commit and provide a mapping table in migration docs.

If retaining them, explicitly mark them deprecated and target 1.0 for removal.

### 12. Consider removing public `SCHEMA_VERSION` alias

`versioning.py` currently contains:

```python
# Compatibility alias retained for existing callers.
SCHEMA_VERSION = CURRENT_SCHEMA_VERSION
```

This is another possible 0.3 cleanup.

A cleaner public contract is:

```text
CURRENT_SCHEMA_VERSION
SUPPORTED_SCHEMA_VERSIONS
```

However this change has lower value than the config cleanup. Only remove it if you are intentionally pruning compatibility aliases in the same release.

Internally, replace uses with `CURRENT_SCHEMA_VERSION` first.

---

## Phase 5 — Release documentation and ledger

### 13. Add 0.3.0 releaseledger entries

Do not manually edit generated changelog output.

Capture:

- SSMD 0.9-only dependency/contract
- explicit-break precedence fix
- package typing marker fix
- selected breaking API changes
- phrasplit provider-doc integration
- migration instructions

### 14. Add a dedicated 0.2 -> 0.3 migration section

Example:

```markdown
## Migrating from UtterPlan 0.2 to 0.3

### SSMD sources

UtterPlan 0.3 accepts SSMD 0.9 only.

Migrate older source files first:

    ssmd migrate FILE --to 0.9

### Python input format

PlannerConfig now defaults to plain text. Set document_format="ssmd"
when compiling SSMD fragments/documents.

### SSMD configuration

strict_header and unknown_header were removed because header validation
is owned by SSMD 0.9.

[If accepted:]
parse_header was renamed to parse_yaml_header.
pause_defaults was renamed to pause_overrides.

### Existing UtterPlan JSON

Serialized schema v1 and v2 remain loadable through the existing migration
chain to schema v3. No SSMD reparse is performed.
```

---

# 17. Suggested file touch list

Minimum required for release blockers:

```text
utterplan/py.typed                         ADD
utterplan/pauses.py                        MODIFY
tests/test_pauses.py                       MODIFY
tests/test_ssmd_09_parser.py               MODIFY
.github/workflows/tests.yml                MODIFY
.github/workflows/python-publish.yml       MODIFY
.ledger/releaseledger/...                  ADD/UPDATE via releaseledger
docs/changelog.md                          REGENERATE
```

Recommended 0.3 API cleanup:

```text
utterplan/config.py
utterplan/parsers.py
utterplan/planner.py
README.md
docs/getting-started.md
docs/python-api.md
docs/consumer-guide.md
docs/cli.md
examples/*
tests/*
tests/golden/*
```

phrasplit integration improvement:

```text
utterplan/planner.py
utterplan/linguistics.py                   only if helper typing/refactor is useful
tests/test_linguistics.py
tests/test_pauses.py                       if clause pause behavior is covered there
```

Optional alias cleanup:

```text
utterplan/model.py
utterplan/versioning.py
utterplan/format.py
utterplan/__init__.py
docs/python-api.md
docs/consumer-guide.md
tests/test_schema_registry.py
```

---

# 18. Suggested acceptance tests

The coding agent should ensure at least the following behavior.

## SSMD dialect

```python
# 0.9 accepted
plan('---\nssmd_version: "0.9"\n---\nHello.')

# 0.8 rejected
raises_code(
    '---\nssmd_version: "0.8"\n---\nHello.',
    "header.version_unsupported",
)

# legacy 0.8 syntax rejected even without a version header
raises_code(
    '[Hello]{volume="loud", rate="fast"}',
    "syntax.comma_separator_legacy",
)
```

## Pause precedence

```text
explicit 200ms break + sentence default 600ms -> 200ms
explicit 0ms break + sentence default 600ms   -> 0ms
paragraph default 1.0s + sentence default 0.6s with no explicit break -> 1.0s
```

## Default format

```python
PlannerConfig(language="en-us").document_format == "plain"
```

SSMD tests explicitly set:

```python
document_format="ssmd"
```

## Header config

Removed fields raise normal constructor errors:

```python
SSMDConfig(strict_header=True)   # invalid in 0.3
SSMDConfig(unknown_header="warn")  # invalid in 0.3
```

SSMD itself remains source of header diagnostics.

## phrasplit

```text
fallback linguistic provider -> no syntactic clausal-comma guesses
spaCy provider_doc            -> high-confidence phrasplit clause boundaries
sentence offsets              -> unchanged between both cases
```

## Packaging

Wheel and sdist contain:

```text
utterplan/py.typed
utterplan/utterplan.schema.json
utterplan/schemas/v1.schema.json
utterplan/schemas/v2.schema.json
utterplan/schemas/v3.schema.json
```

METADATA contains:

```text
phrasplit >=0.3.9,<0.4
ssmd >=0.9.0,<0.10
spokenform >=0.4.3,<0.5
```

---

# 19. Release gate / definition of done

Do not tag `v0.3.0` until all items below are true.

- [ ] `utterplan/py.typed` exists in source.
- [ ] Wheel contains `py.typed`.
- [ ] Wheel contains all v1/v2/v3 schemas and current schema alias.
- [ ] Lower-bound CI installs `ssmd==0.9.0`.
- [ ] Publish validation requires `ssmd>=0.9.0`.
- [ ] No supported/runtime path depends on SSMD 0.8.
- [ ] 0.8 source-header rejection test is green.
- [ ] Legacy 0.8 syntax rejection test is green.
- [ ] Explicit SSMD source break precedence follows the 0.9 specification.
- [ ] Focused SSMD tests are green.
- [ ] Full pytest suite is green in clean CI with installed dependencies.
- [ ] Ruff is green.
- [ ] mypy is green.
- [ ] Documentation builds with warnings treated as errors.
- [ ] Installed-wheel CLI smoke test compiles strict SSMD 0.9.
- [ ] Installed-wheel smoke test rejects explicit SSMD 0.8.
- [ ] v1 and v2 UtterPlan plan migration tests remain green.
- [ ] Selected 0.3 breaking API changes are documented.
- [ ] Releaseledger contains accepted 0.3.0 entries.
- [ ] Generated changelog contains 0.3.0 notes.
- [ ] Tag-derived package version equals `0.3.0`.
- [ ] Final clean build produces exactly the expected wheel and sdist.

---

# 20. Proposed final 0.3.0 scope

I would make 0.3.0 contain this set and stop there:

## Must have

1. SSMD 0.9 only.
2. Explicit-break precedence fix.
3. CI/publish pins corrected to SSMD 0.9.0.
4. `py.typed` added.
5. Full clean CI/releaseledger completion.

## Breaking improvements worth including

6. Python default format becomes `plain`.
7. Remove `SSMDConfig.strict_header`.
8. Remove `SSMDConfig.unknown_header`.
9. Rename the SSMD pause application override if you are willing to update config consumers now.
10. Reuse phrasplit/spaCy provider docs for syntactic clause detection.
11. Remove the unused segmentation analysis parameter / duplicate internal phrasplit integration.

## Defer unless downstream usage is still entirely controlled

12. Remove model compatibility aliases.
13. Remove `SCHEMA_VERSION` alias.

This scope improves correctness and makes the API easier to explain without turning 0.3.0 into a broad rewrite.

---

# 21. Bottom line for the coding agent

The repository is **close, but not release-ready in the audited state**.

The SSMD 0.9 migration itself is largely successful. Do not redesign the parser integration. Fix the one semantic precedence conflict, remove the stale 0.8 workflow expectations, restore the missing typing marker, then use the 0.3 boundary to simplify the misleading/no-op configuration surface and make plain text the safe Python default.

Preserve old compiled-plan migration support. Keep sentence segmentation deterministic. Reuse existing spaCy analysis only for enrichment that explicitly benefits from it.

After these changes, run the full clean release matrix and only then tag 0.3.0.
