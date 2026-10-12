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
