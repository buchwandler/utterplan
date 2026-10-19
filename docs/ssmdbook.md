# Compiling chapters from an SSMDBook

UtterPlan's `compile-book` command accepts an editable `.ssmdbook` workspace as a collection of independent SSMD 0.9 chapter sources. It reads the workspace manifest to discover chapter paths and source numbers, then delegates the selected documents to the existing incremental batch compiler. Each successful chapter becomes its own canonical UtterPlan v7 plan; UtterPlan does not create a combined book plan or modify the source workspace.

## Quick start

From the book root, select an inclusive source chapter range:

```bash
cd "Platform Decay - Martha Wells.ssmdbook"

utterplan compile-book chapters --chapters 5-17
```

The output defaults to `<book-root>/utterplan/`:

```text
utterplan/
├── compile-report.toml
├── chapter-0005.utterplan.toml
├── chapter-0006.utterplan.toml
├── ...
└── chapter-0017.utterplan.toml
```

The equivalent explicit-root form is:

```bash
utterplan compile-book "Platform Decay - Martha Wells.ssmdbook" --chapters 5-17
```

You may also run `utterplan compile-book chapters` to compile every chapter in the manifest, or select a non-contiguous set:

```bash
utterplan compile-book chapters --chapters 1,3-5
```

Use `--output-dir PATH` to choose another plan directory. The output directory and report path are preflighted for collisions. Plans are protected if they already exist unless `--force` is supplied. The normal batch behavior continues after a chapter failure; use `--fail-fast` to skip later chapters after the first failure. The TOML `compile-report.toml` records each selected item and its outcome; it is operational metadata, not a FlowPlan.

The version-2 report records each successful chapter's resolved preparation mode, repair count, ordered structured repair diagnostics, and whether linguistic token metadata was degraded. Source ranges in diagnostics refer to Python-character positions in the original chapter file. These details do not change per-chapter atomic writes or incremental failure behavior.

## Workspace discovery and selection

`INPUT` must be either:

- an SSMDBook root containing `manifest.json`; or
- its canonical `chapters/` directory, whose parent contains `manifest.json`.

The manifest is the format authority; the root directory does not need a `.ssmdbook` suffix. UtterPlan accepts the SSMDBook v1 contract (`format: "ssmdconvert.book"`, `schema_version: 1`, `ssmd_version: "0.9"`). Chapter selection uses each entry's `source_number`, not the filename or position in the manifest. Supported selectors are:

- `all` (default)
- `5`
- `5-17`
- `1,3-5,9`

Ranges are inclusive. Numbers must be positive and present in the manifest. Reversed or malformed ranges and missing source numbers are usage errors. Duplicate selected numbers are compiled once. Results follow authoritative manifest array order; they are not sorted by filename or number.

Only selected chapter source files are opened by the compiler. A malformed or missing unselected chapter does not block a subset compilation. Selected source read, SSMD validation, planning, and write errors are handled as batch item failures, preserving successful outputs and the report.

## Editable workspace behavior and safety

An SSMDBook directory is an editable workspace. If a selected chapter was edited after the manifest was written, UtterPlan compiles the current file content even when its recorded `sha256` is stale. It never refreshes digests or edits `manifest.json` or chapter files. Chapter paths are checked as normalized relative POSIX paths below `chapters/`; absolute paths, drive prefixes, traversal, unsafe symlink escapes, and non-regular selected targets are rejected. Plans and reports may not be written into the source `chapters/` directory or over the manifest.

`compile-book` shares these planning options with `compile-many`:

- `--language` / `--lang`
- `--text-preparation auto|ssmd|spokenform|identity`
- `--renderability strict|repair`
- `--spacy auto|off|sm|md|lg|trf`
- `--force`, `--fail-fast`, and `--report PATH`

Compilation always uses paragraph-local flow units; `compile-book` has no renderer `--unit` or pause-mode selection. Schema-v7 segments preserve safe boundary opportunities separately from authored SSMD pause intents, so a consumer may later choose sentence-, paragraph-, or token-budget-based chunks and its own native, automatic, or manual pause behavior. A `FlowSegment` is not necessarily a TTS request, and UtterPlan's linguistic tokens are not renderer token counts.

`compile-book` uses the same best-effort spaCy `auto` default as `compile`: installed models are preferred in `sm`, `md`, `lg`, `trf` order and missing resources fall back safely. `--spacy off` forces fallback; explicit tier flags require that local model.

Chapter input is SSMD by contract, so `compile-book` deliberately has no `--input-format` option. When no `--language` is supplied, a selected chapter must declare its language in SSMD metadata.

## From semantic chapter plans to RenderPlan variants

The complete file-based workflow keeps UtterPlans renderer-neutral while allowing
several independent RenderPlan collections for one book:

```text
SSMD chapters
    -> utterplan/*.utterplan.toml
    -> renderplan/<profile-label>--<profile-id-prefix>/*.renderplan.toml
```

Create engine-backed RenderProfiles with VoiceRender, compile chapters once, then
project them using `utterplan render-book`:

```bash
voicerender profile create \
  --engine piper --target en_US-amy-medium --language en-US \
  --offline --output amy.renderprofile.toml
voicerender profile create \
  --engine piper --target en_US-joe-medium --language en-US \
  --offline --output joe.renderprofile.toml

utterplan compile-book . --chapters 5-17
utterplan render-book . --profile amy.renderprofile.toml --chapters 5-17
utterplan render-book . --profile joe.renderprofile.toml --chapters 5-17
```

One RenderProfile is the complete cast shared by every selected chapter, not a profile per character or role. Logical role names live in SSMD; the profile's role bindings can target different renderers. Before creating a new variant, `render-book` checks all readable selected UtterPlans together and reports every uncovered role with the affected chapter IDs. See the [README role example](https://github.com/buchwandler/utterplan/blob/main/README.md#logical-roles-and-complete-renderprofiles).

The result has one shared semantic collection and distinct renderer-specific
variants, for example:

```text
utterplan/
├── chapter-0005.utterplan.toml
└── ...
renderplan/
├── amy--<profile-id-prefix>/
│   ├── renderprofile.toml
│   ├── renderplan-set.toml
│   ├── render-report.toml
│   └── chapter-0005.renderplan.toml
└── joe--<profile-id-prefix>/
    └── ...
```

A variant is keyed by the canonical full RenderProfile `profile_id`; its directory
uses a readable label plus a short fingerprint. A semantic profile change selects
a new default directory instead of overwriting an earlier voice or policy. The
snapshot is the profile authority for that collection; the UtterPlan-owned
`renderplan-set.toml` records the full identity, original profile reference, and
per-chapter source/render plan identities. `render-report.toml` describes only the
latest invocation, while the set index accumulates successful chapters across
ranges.

UtterPlan structurally loads the shared profile through RenderPlan and does not
import VoiceRender, inspect engine availability, preflight requests, or synthesize.
VoiceRender is responsible for profile creation/refresh and downstream preflight
and synthesis; it is not required merely to run `render-book`. A later
`render-book` invocation still needs the profile passed on its command line, while
the collection's snapshot remains available for inspection and reproducible
replanning. See the [CLI reference](cli.md#produce-renderplans-for-selected-ssmdbook-chapters),
[RenderPlan](https://pypi.org/project/renderplan/), and
[VoiceRender](https://pypi.org/project/voicerender/).

## Python API for SSMDBook workspaces

The Python API and CLI share the same book orchestration and artifact layout. The public services read the manifest for chapter discovery, select by original `source_number`, validate safe workspace paths, and write the same reports and per-chapter plans as the commands above. They do not print to the console or retain CLI argument objects.

CLI:

```bash
utterplan compile-book . --chapters 5-17
utterplan render-book . --profile narration.renderprofile.toml --chapters 5-17
```

Equivalent Python:

```python
from utterplan import compile_book, render_book

compiled = compile_book(".", chapters="5-17")
projected = render_book(
    ".",
    profile="narration.renderprofile.toml",
    chapters="5-17",
)

print(projected.variant)  # exact profile-specific RenderPlan directory name
```

`BookCompileResult` and `BookRenderResult` expose the resolved workspace, selector, selected chapter IDs, artifact/report paths, per-chapter outcomes, `failed`, and `exit_code`. `BookRenderResult.variant` is the final sanitized label plus profile fingerprint; consumers should use it rather than reproduce the naming algorithm. Optional `on_progress` callbacks receive each compile or projection outcome, and `on_start` callbacks receive resolved selection and output metadata. A chapter must declare its language unless `language=` is explicitly supplied to `compile_book()`; compiler behavior can otherwise be configured with `planner_config=`. Invalid workspaces and unsafe paths raise `BookServiceError`, while ordinary per-chapter failures are represented in outcomes.

The public request models `BookCompileRequest` and `BookRenderRequest` capture the corresponding service options. These APIs remain engine-independent: they neither inspect TTS engines nor synthesize or compose audio.
