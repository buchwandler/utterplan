# Command-line interface

UtterPlan's command-line compiler accepts literal text, stdin, and files:

```text
usage: utterplan compile [-h] [--file FILE] [--language LANGUAGE]
                         [--input-format {auto,text,plain,ssmd}]
                         [--text-preparation {auto,ssmd,spokenform,identity}]
                         [--spacy {auto,off,sm,md,lg,trf}] [-o OUTPUT]
                         [--trace TRACE] [--force] [--stdout]
                         [--renderability {strict,repair}]
                         [text ...]
```

`--lang` is an alias for `--language`; the older `--format` spelling is accepted
as an alias for `--input-format`. `--language` is a fallback language: it is
required for plain input, optional for SSMD with a header `language`, and never
forces a language over SSMD document semantics.

## Renderer-independent plan contract

Compilation has no `--unit` or `--pause-mode` option. Schema v7 always stores paragraph-local flow units and canonical `boundary_before` / `boundary_after` opportunities (`clause`, `sentence`, `paragraph`, `parenthetical`, `voice_change`) separately from authored SSMD pause intents. One saved plan can support downstream sentence, paragraph, or renderer-token-budget chunking, and native, automatic, or manual pause realization. A `FlowSegment` is not necessarily a TTS call; its linguistic token views are not engine/model token counts.

## Input resolution

The rules are deterministic:

1. `--file FILE` reads exactly that UTF-8 file and cannot be combined with
   positional text.
2. With no positional text or `--file`, stdin is read. An empty terminal or
   empty stdin is an error.
3. `--input-format text` and `--input-format plain` interpret positional tokens as literal text.
4. Otherwise, one positional token naming an existing regular file is read.
5. All remaining positional tokens are joined with single spaces as literal
   text.

With `auto`, `.ssmd` and `.ssmd.md` files are interpreted as SSMD. Markdown files
with an SSMD version header are also detected as SSMD; ordinary Markdown remains
plain text; literal text and stdin default to plain. Use `--input-format ssmd`
explicitly for SSMD from stdin or unversioned canonical fragments. All SSMD inputs
are parsed as strict dialect 0.9.

The SSMD header's `language` wins over `--language`. When the header declares a
language, no CLI language is needed. If it does not, provide `--language` as the
fallback; plain input always requires that option:

```bash
utterplan compile chapter.ssmd.md
utterplan compile legacy.ssmd.md --language de-DE
utterplan compile plain.txt --input-format plain --language de-DE
```

## SSMD source compatibility

UtterPlan accepts SSMD 0.9 syntax only. It does not auto-migrate older source or provide a legacy parser. Convert an old SSMD file before compilation:

```bash
ssmd migrate old.ssmd --to 0.9 --output migrated.ssmd
utterplan compile migrated.ssmd --lang en-us
```

`utterplan migrate` handles serialized-plan migrations only; v6-to-v7 promotion returns `migration.recompile_required` instead of writing an incomplete current plan. It cannot migrate SSMD source.

## Output and errors

Without `--output`, compile writes the pretty TOML plan to stdout. With
`--output`, the TOML file is written and an existing file is refused unless
`--force` is supplied. Add `--stdout` with an output path to write the file and
also emit the same TOML plan to stdout.

`--trace PATH` writes optional compiler provenance to a separate TOML sidecar. The trace is not embedded in, or hashed as part of, the executable plan. The plan itself stores exact raw source when available; keep and distribute the sidecar when preparation maps, diagnostics, renderability evidence, or source-coordinate mappings must be retained.
Human status messages are written to stderr, never mixed into TOML stdout:

```bash
utterplan compile chapter.ssmd.md -o chapter.utterplan.toml
# status is written to stderr
utterplan compile chapter.ssmd.md -o chapter.utterplan.toml --stdout
```

Argparse usage errors use exit code 2. Input, planning, file, and plan
validation errors use exit code 1 and are reported without a traceback.

## Compile many documents incrementally

`compile-many` reads source files in the requested order, compiles each independently, and atomically saves each successful plan before reading the next. Ordinary input, planning, and write failures are reported per item and do not roll back earlier plans; processing continues unless `--fail-fast` is set.

```bash
utterplan compile-many chapters/*.ssmd --output-dir build/plans \
  --language en-us --report build/compile-report.toml
```

Source names determine output names: `chapter.ssmd`, `chapter.ssmd.md`, and `chapter.md` each map to `chapter.utterplan.toml`. Duplicate output names and a report path that collides with a plan output are rejected before any writes. Existing plans are protected unless `--force` is supplied. By default the command writes an atomically refreshed `compile-report.toml` in the output directory; the report is operational TOML, not a plan accepted by `FlowPlan.load()`.

Compile reports use format version 2. Each successful item records its resolved `preparation_mode`, `repair_count`, deterministically ordered structured `repairs`, and a `degraded_linguistics` boolean. Repair entries include diagnostic codes/messages/severity and source ranges where available; source ranges use the original input's Python-character coordinates. Failed or skipped items have no preparation result. Reports remain operational metadata and do not affect plan output or incremental write behavior.

Shared planning options include `--language`, `--input-format auto|plain|ssmd`, `--text-preparation`, `--spacy`, and `--renderability`. Progress, repair notices, actionable errors, and the final counts are written to stderr. Exit status is 0 if every input succeeds, 1 if any input fails, and 2 for usage errors such as output collisions. `--fail-fast` skips later requests after the first failure but preserves all completed outputs and updates the report.

## Compile chapters from an SSMDBook workspace

`compile-book` discovers selected SSMD chapters from an editable `.ssmdbook` manifest and compiles each chapter independently through the batch compiler. Pass either the book directory or its canonical `chapters/` directory:

```bash
utterplan compile-book novel.ssmdbook --chapters 5-17
utterplan compile-book novel.ssmdbook/chapters --chapters 1,3-5
```

The workflow used from inside the workspace is:

```bash
cd "Platform Decay - Martha Wells.ssmdbook"

utterplan compile-book chapters --chapters 5-17
```

`--chapters` selects manifest `source_number` values, not filenames or manifest indexes. It accepts `all` (the default), one number, inclusive ranges, or comma-separated combinations such as `1,3-5,9`. Duplicate selections do not duplicate work, and selected chapters always follow manifest array order. A selected missing source number or malformed selector is rejected before compilation.

By default, plans and the operational report are written to `<book-root>/utterplan/`. Use `--output-dir PATH` to override the destination. One canonical v7 `.utterplan.toml` plan is written per selected chapter, plus `compile-report.toml`. Existing plans are protected unless `--force` is given; `--fail-fast` skips later chapters after the first failure. `--report PATH` overrides the report location. Duplicate output names, report/plan collisions, and writes into the source `chapters/` directory or over `manifest.json` are rejected before writing.

Shared planning options are `--language`/`--lang`, `--text-preparation`, `--renderability`, and `--spacy`. Chapter documents are SSMD 0.9 by contract, so `compile-book` does not accept `--input-format`. The manifest is read-only: edited chapter content is compiled as it currently exists even if its recorded digest is stale, and UtterPlan never refreshes the manifest or chapter hashes. Only selected chapter files are opened, so an unrelated broken chapter outside the selection does not block the request.

The version-2 compile report identifies each successful chapter's resolved preparation mode (`ssmd`, `spokenform`, or `identity`), reports a deterministic list of segmentation/renderability repair diagnostics and a `degraded_linguistics` flag, and includes a `repair_count`. The report is operational metadata; partial-success, atomic per-plan writes, and manifest immutability are unchanged.

For the full editable-workspace behavior and examples, see the [SSMDBook guide](ssmdbook.md).

## Explain a plan

Explain an existing compiled plan as a human-readable speech narrative:

```bash
utterplan explain chapter.utterplan.toml
utterplan explain chapter.utterplan.toml --details
```

The explanation presents executable flow: prepared segment text, paragraph-local unit order, effective languages, canonical boundary opportunities, authored pause intents, headings, markers, and typed directives. The v7 plan retains exact raw source when available and compact replacement views show local prepared surfaces with original spellings. Complete compiler source diagnostics and preparation maps remain absent unless a trace sidecar was saved. Add `--details` for local token offsets, flow hashes, plan identity, and trace preparation mappings. Pass `--trace PATH` to attach a matching sidecar; the TOML trace can also be read independently with `inspect-trace`.

## Inspect a persisted planning attempt

`inspect` reads canonical plans. Persistable planning outcomes use the separate
`utterplan.planning-attempt.v1` artifact and are opened with `inspect-attempt`:

```bash
utterplan inspect-attempt chapter.attempt.toml
utterplan inspect-attempt chapter.attempt.toml --issues
utterplan inspect-attempt chapter.attempt.toml --segment seg-000001 --unit unit-000001
utterplan inspect-attempt chapter.attempt.toml --json
```

The default view summarizes status, renderability, and candidate size. `--issues`
shows source context and conservative repair assessments; segment and unit selectors
accept an ID or zero-based index. `--json` emits the complete artifact as JSON for
inspection, but the persisted attempt itself remains TOML. A blocked candidate is an
inspect-only draft, not a canonical plan, and is rejected by `FlowPlan.load()`.

## Planning controls

- `--text-preparation auto|ssmd|spokenform|identity` chooses written-to-spoken handling.
- `--spacy off|auto|sm|md|lg|trf` selects deterministic fallback, automatic
  spaCy use, or a required model tier.
- `--renderability repair|strict` defaults to safe punctuation-only repair. Semantic blockers remain failures with source context and an actionable next step; strict mode reports safe repair opportunities without applying them.

The default spaCy policy is `auto`: inspect only already-installed compatible local models in `sm`, `md`, `lg`, `trf` preference order. If spaCy or every compatible model is unavailable, compilation continues with deterministic fallback; no model is downloaded.

The defaults are `--text-preparation auto` and `--spacy auto`. Preparation `auto` selects authoritative `ssmd` for SSMD input and TTSReady/Spokenform for plain text; explicit `spokenform` on SSMD is a warned legacy mode. SpaCy `auto` uses a compatible local model when available and otherwise falls back safely. Compilation does not select renderer chunking or pause realization: schema-v7 boundaries and authored pause intents are realized downstream.

Use `--spacy off` to force deterministic fallback. `--spacy sm|md|lg|trf` requires that local model tier and fails if it is unavailable. Token columns in v7 carry final prepared-text linguistic context, not model-token counts; the optional `replacement` fields describe local output spans, not source coordinates. Preserve the trace sidecar for full source maps and preparation diagnostics.

## Other commands

```bash
utterplan --version
utterplan validate chapter.utterplan.toml
utterplan validate chapter.ssmd.md
utterplan validate plain.txt --input-format plain --language en-us
utterplan inspect chapter.utterplan.toml --segment 0
utterplan inspect chapter.utterplan.toml --unit 0 --boundaries --tokens
utterplan compile chapter.ssmd.md -o chapter.utterplan.toml --trace chapter.trace.toml
utterplan explain chapter.utterplan.toml --trace chapter.trace.toml
utterplan inspect-trace chapter.trace.toml --preparation --boundaries
utterplan inspect-attempt chapter.attempt.toml --issues
```

`inspect --unit` selects a stored flow unit for inspection; it does not choose compilation grouping. Compilation always writes paragraph-local flow blocks, and downstream renderers choose their own chunk boundaries from the saved boundary opportunities.

`inspect-trace --preparation` reports source/prepared text lengths, maps, preparation changes, and repair/diagnostic evidence from the optional trace. `inspect-trace --boundaries` shows compiler-only boundary events and semantic candidates. These fields are intentionally absent from the executable plan TOML.

## Migrate a saved plan

Use `utterplan migrate` to inspect sequential data-only migrations for legacy saved plans. Schema-v6 files cannot prove the complete v7 boundary inventory, so promotion intentionally fails with `migration.recompile_required`; recompiling the original source is the supported route to a current plan.

```bash
utterplan migrate old.utterplan.json --check
utterplan compile source.ssmd.md -o current.utterplan.toml
```

When a migration is available, `-o` writes TOML to that path, while stdout and status messages remain separated; an existing output requires `--force`. `--check` reports source and target schema without writing. A historical plan that reaches schema v6 is rejected with `migration.recompile_required` because boundary opportunities cannot be recovered from serialized data; the CLI never silently reparses or replans. Future schema versions are rejected rather than guessed or downgraded.

Schema migration is separate from SSMD source migration. Frozen JSON schemas v1–v4 and saved schema-v5 TOML use the registered sequential path through schema v6; v6-to-v7 conversion reports `migration.recompile_required` rather than fabricating boundaries. These migrations do not rerun parsing, text preparation, NLP, or planning; the v5-to-v6 step preserves compiled flow and leaves unavailable source provenance absent. The v4-to-v5 projection refuses ambiguous token coordinates or pause meanings rather than guessing. Use `ssmd migrate FILE --to 0.9` for older SSMD source documents.

For a saved TOML plan, `validate` verifies the current semantic schema and plan
invariants; JSON plan paths are rejected outside `migrate`. For an SSMD or
plain-text source document, it runs the canonical one-document semantic compiler
without writing a plan; plain input requires `--language`, while SSMD can use its
header language or an explicit fallback.
