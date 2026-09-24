---
goal: "Complete the UtterPlan 0.3.0 release-audit changes in @01_todo.md while preserving schema v1/v2 migration support and stopping before publication or tagging."
files:
  - "@01_todo.md"
  - "@utterplan/pauses.py"
  - "@utterplan/config.py"
  - "@utterplan/planner.py"
  - "@.github/workflows/tests.yml"
  - "@.github/workflows/python-publish.yml"
  - "@pyproject.toml"
  - "@docs/changelog.md"
  - "@docs"
  - "@tests"
test_commands:
  - "pytest -q"
  - "ruff check ."
  - "mypy utterplan"
  - "python -m sphinx -W --keep-going -b html docs docs/_build/html"
  - "python -m build"
expected_outputs:
  - "Explicit SSMD source breaks win at shared boundaries, including zero-duration breaks, while all contributor IDs are retained."
  - "The supported SSMD dependency contract is >=0.9.0,<0.10 in runtime metadata, CI, publish checks, and built artifacts."
  - "The wheel and sdist contain py.typed and every immutable v1/v2/v3 schema resource."
  - "Plain text is the PlannerConfig default, obsolete SSMD config options are removed, and accepted configuration renames are documented."
  - "Provider-owned linguistic docs are reused for clausal boundaries without changing deterministic sentence segmentation or rerunning NLP."
  - "Tests, lint, typing, documentation, CLI smoke tests, and package artifact checks pass where the local environment provides their dependencies."
acceptance_criteria:
  - id: ac-0001
    text: "Explicit SSMD source breaks take precedence over generated/default pauses at a shared boundary, including an authored 0ms break; no durations are added and all event IDs remain in provenance."
    mandatory: true
  - id: ac-0002
    text: "UtterPlan supports SSMD 0.9 only: supported dependency ranges, CI lower-bound installation, publish metadata validation, and installed-wheel positive/negative smoke tests agree, while 0.8 is rejected and historical UtterPlan schema migrations remain supported."
    mandatory: true
  - id: ac-0003
    text: "The Python API defaults to plain input, removes no-op strict_header and unknown_header options, applies the selected parse_yaml_header and pause_overrides renames, and updates affected code, tests, examples, goldens, and migration documentation."
    mandatory: true
  - id: ac-0004
    text: "Clausal-boundary enrichment reuses an existing spaCy provider document when available, fallback analysis does not guess, sentence segmentation remains deterministic, and dead/duplicate phrasplit integration code is removed or consolidated."
    mandatory: true
  - id: ac-0005
    text: "Wheel and sdist package py.typed, current and historical schema resources, and the correct dependency bounds; package smoke tests verify those contents."
    mandatory: true
  - id: ac-0006
    text: "User-facing migration and release documentation and the project releaseledger/changelog state reflect the selected 0.3.0 changes without inventing a release date or claiming publication."
    mandatory: true
  - id: ac-0007
    text: "The full local test, lint, typing, documentation, CLI smoke, and build checks are run and their actual results recorded; any environment-only inability to run the clean published-dependency GitHub CI gate is reported rather than represented as passed."
    mandatory: true
todos:
  - id: plan-todo-0001
    text: "Fix pause precedence and add direct plus SSMD integration tests for explicit timed/zero breaks and longest-default behavior."
    mandatory: true
    validation_hint: "Run focused pause and SSMD parser tests; verify the source event IDs are retained."
  - id: plan-todo-0002
    text: "Align dependency metadata, CI and publish validation to SSMD 0.9-only; add py.typed and installed-wheel smoke/package-resource checks."
    mandatory: true
    validation_hint: "Inspect all remaining 0.8 references and verify wheel/sdist metadata and contents plus positive/negative CLI smoke cases."
  - id: plan-todo-0003
    text: "Apply the selected 0.3 Python API changes: plain default, remove no-op header options, rename parse_header and pause_defaults, and update all consumers/tests/docs/goldens."
    mandatory: true
    validation_hint: "Run tests and search the repository for stale API names; inspect config serialization goldens and migration guidance."
  - id: plan-todo-0004
    text: "Reuse provider-owned phrasplit docs for clausal boundaries, preserve deterministic sentence splitting, remove the unused analysis parameter, and consolidate duplicate wrapper logic."
    mandatory: true
    validation_hint: "Test provider-doc, fallback, and sentence-offset invariants without invoking spaCy twice."
  - id: plan-todo-0005
    text: "Update 0.2-to-0.3 migration and release documentation, add reviewed 0.3.0 releaseledger entries, and build the requested changelog section without finalizing or tagging the release."
    mandatory: true
    validation_hint: "Use releaseledger workflow and inspect the generated section; do not invent a date or claim shipment."
  - id: plan-todo-0006
    text: "Run the complete test, lint, typing, docs, CLI smoke, and package build matrix; reconcile changed files and record evidence."
    mandatory: true
    validation_hint: "Run pytest, ruff, mypy, Sphinx with warnings as errors, installed-wheel 0.9/0.8 smoke cases, and wheel/sdist artifact checks."
---

# Implement the UtterPlan 0.3.0 release audit

## Summary

Implement the concrete compatibility, package, pause-semantics, API, phrasplit-integration, testing, documentation, and release-ledger work specified in `@01_todo.md`. The audit's explicit recommendations to retain UtterPlan schema v1/v2 migrations and deterministic sentence topology are preserved. API cleanup items marked as selected in the proposed 0.3.0 scope are included, while compatibility aliases and `SCHEMA_VERSION` are deferred because the audit explicitly says to defer them absent evidence that downstream usage is controlled.

## Implementation Changes

- Make authored SSMD breaks outrank automatic/default boundary pauses while retaining all contributors and never summing durations.
- Correct all supported SSMD dependency declarations and checks to `>=0.9.0,<0.10`, add strict installed-package 0.9/0.8 smoke coverage, ensure all schema resources are checked, and add the missing PEP 561 marker.
- Set Python `PlannerConfig.document_format` to `plain`; remove no-op `strict_header` and `unknown_header`; rename `parse_header` to `parse_yaml_header` and `SSMDConfig.pause_defaults` to `pause_overrides` throughout the public surface.
- Reuse request-local spaCy provider docs for syntactic clause enrichment without running NLP twice; retain deterministic sentence splitting; remove unused and duplicate internal phrasplit integration.
- Document the 0.2-to-0.3 migration, SSMD source migration, configuration changes, and preserved serialized-plan migration path. Add reviewed 0.3.0 releaseledger entries and build an undated/unreleased 0.3.0 changelog section only after releaseledger checks permit it.
- Leave Git publication/tagging and final release completion to a separately authorized release action. Do not claim a clean GitHub run if only local checks were possible.

## Tests

- Add and run direct pause-resolution and parser/planner integration tests, including zero-duration explicit breaks and competing defaults.
- Run the complete pytest suite, `ruff check .`, `mypy utterplan`, and the Sphinx warnings-as-errors documentation build.
- Build wheel and sdist; inspect dependency metadata and ensure both artifacts contain the typing marker and v1/v2/v3 plus current schema resources.
- Exercise an installed wheel with a strict SSMD 0.9 document and verify an explicit SSMD 0.8 header is rejected.
- Preserve and run schema v1/v2 migration tests. Report any unavailable environment or published-dependency CI checks precisely.

## Assumptions

- "Implement everything" includes the selected API changes and the conditional configuration renames in the proposed final scope.
- The audit explicitly defers model compatibility-property removal and the `SCHEMA_VERSION` alias unless downstream usage is known to be controlled; neither will be removed without that evidence.
- No release date or shipment intent was provided, so releaseledger state and changelog output remain planned/unreleased. No Git tag, package publication, or release finalization is authorized by this task.
- The task can prepare workflow changes and run local equivalents, but cannot claim a clean GitHub CI run against published dependencies unless that run is actually available.

## Out of Scope

- Creating/pushing a Git tag, publishing packages, finalizing a shipped release, or assigning an unprovided release date.
- Removing model compatibility aliases or the `SCHEMA_VERSION` alias.
- Dropping serialized UtterPlan schema v1/v2 migration support, adding schema v4, making sentence topology spaCy-dependent, or moving renderer/provider behavior into UtterPlan.
- Changes in sibling consumer checkouts.
