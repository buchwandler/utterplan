---
schema_version: 4
id: content-0007
kind: content
type: section
section: deployment_view
title: Deployment View
order: 70
status: accepted
version: 5
body_format: markdown
---

UtterPlan deploys as a single pure-Python package with no engine, model runtime,
or audio dependencies:

- **Distribution.** Published on PyPI as `utterplan`; the package version is
  dynamically derived from Git tags by setuptools-scm and is independent of the
  plan schema version.
- **Installation shapes.** Installed as a library (`pip install utterplan`) for
  downstream FlowPlan consumers, or with the `utterplan` CLI for canonical
  manifest-driven `.ssmd-bundle/` workflows. Development installs use
  `pip install -e '.[dev,docs]'`.
- **Optional linguistic enrichment.** spaCy models are preferred in `sm`, `md`,
  `lg`, `trf` order when already installed; UtterPlan never downloads models and
  continues with deterministic fallback tokens when spaCy or every compatible local
  model is unavailable. Explicit tiers can be required via configuration.
- **No runtime services.** Everything runs in-process; there is no server, daemon,
  network fetch, or audio device access. Media references and extension names in
  plans are data only.
- **Downstream placement.** Consumers of UtterPlan's portable FlowPlan and optional
  RenderPlan contracts add engines, model runtimes, G2P, synthesis, and audio on their
  side of the boundary; UtterPlan does not import those packages.
- **Documentation.** Sphinx docs build from `docs/` with
  `sphinx-build -W --keep-going -b html docs docs/_build/html`.
- **Quality gate.** `python -m pytest -q`, `ruff check .`, and `mypy utterplan` run
  against the self-contained repository test suite.

- **Manifest-driven bundle lifecycle.** Schema-v1 book and document manifests use
  the same canonical `.ssmd-bundle/` root and unified `bundle` compile, render,
  and replan services. Source content and manifests remain read-only.
