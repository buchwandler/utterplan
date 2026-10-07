# Command-line interface

UtterPlan's command-line compiler accepts literal text, stdin, and files:

```text
usage: utterplan compile [-h] [--file FILE] [--language LANGUAGE]
                         [--input-format {auto,text,plain,ssmd}]
                         [--unit {paragraph,sentence}]
                         [--text-preparation {spokenform,identity}]
                         [--pause-mode {tts,manual,auto}]
                         [--spacy {auto,off,sm,md,lg,trf}] [-o OUTPUT]
                         [--force] [--stdout] [--renderability {strict,repair}]
                         [text ...]
```

`--lang` is an alias for `--language`; the older `--format` spelling is accepted
as an alias for `--input-format`. `--language` is a fallback language: it is
required for plain input, optional for SSMD with a header `language`, and never
forces a language over SSMD document semantics.

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

`utterplan migrate` is the explicit JSON-plan import path: it applies supported schema migrations and writes canonical TOML. It cannot migrate SSMD source.

## Output and errors

Without `--output`, compile writes the pretty TOML plan to stdout. With
`--output`, the TOML file is written and an existing file is refused unless
`--force` is supplied. Add `--stdout` with an output path to write the file and
also emit the same TOML plan to stdout.

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

Source names determine output names: `chapter.ssmd`, `chapter.ssmd.md`, and `chapter.md` each map to `chapter.utterplan.toml`. Duplicate output names and a report path that collides with a plan output are rejected before any writes. Existing plans are protected unless `--force` is supplied. By default the command writes an atomically refreshed `compile-report.toml` in the output directory; the report is operational TOML, not a plan accepted by `UtterancePlan.load()`.

Shared planning options include `--language`, `--input-format auto|plain|ssmd`, `--unit`, `--text-preparation`, `--pause-mode`, `--spacy`, and `--renderability`. Progress, repair notices, actionable errors, and the final counts are written to stderr. Exit status is 0 if every input succeeds, 1 if any input fails, and 2 for usage errors such as output collisions. `--fail-fast` skips later requests after the first failure but preserves all completed outputs and updates the report.

## Explain a plan

Explain an existing compiled plan as a human-readable speech narrative:

```bash
utterplan explain chapter.utterplan.toml
utterplan explain chapter.utterplan.toml --details
```

The default output shows prepared wording, render units, ordered segments, languages, resolved pauses, headings, SSMD version/title/document language, effective typed directives, metadata, and warning/error codes with source locations. Add `--details` for IDs, offsets, provenance, hashes, plan identity, and token analysis beneath each segment. Use `inspect --tokens` for a compact token/provenance view.

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
inspect-only draft, not a canonical plan, and is rejected by `UtterancePlan.load()`.

## Planning controls

- `--unit paragraph|sentence` chooses render-unit grouping.
- `--text-preparation spokenform|identity` chooses written-to-spoken handling.
- `--pause-mode tts|manual|auto` selects semantic pause policy.
- `--spacy off|auto|sm|md|lg|trf` selects deterministic fallback, automatic
  spaCy use, or a required model tier.
- `--renderability repair|strict` defaults to safe punctuation-only repair. Semantic blockers remain failures with source context and an actionable next step; strict mode reports safe repair opportunities without applying them.

The default spaCy policy is `off`, so the CLI does not depend on whichever optional model happens to be installed.

The complete defaults are `--text-preparation spokenform`, `--pause-mode tts`, and `--spacy off`. `spokenform` is the default text-preparation backend, while `tts` is the default pause mode. `--spacy off` uses UtterPlan's deterministic fallback tokenizer and analysis and does not require an installed spaCy model.

Use `--spacy auto` only as an opt-in enrichment policy. If a compatible local model is available, it may provide richer tokenization, POS tags, lemmas, and tags; `auto` is not the default and no model is downloaded automatically.

## Other commands

```bash
utterplan --version
utterplan validate chapter.utterplan.toml
utterplan validate chapter.ssmd.md
utterplan validate plain.txt --input-format plain --language en-us
utterplan inspect chapter.utterplan.toml --segment 0
utterplan inspect chapter.utterplan.toml --unit 0 --boundaries --tokens
utterplan inspect chapter.utterplan.toml --preparation
utterplan inspect chapter.utterplan.toml --semantic-boundaries
utterplan inspect-attempt chapter.attempt.toml --issues
```

`inspect --preparation` reports the preparation backend and version, structural and spoken text lengths, replacement count, and each replacement's structural and spoken ranges and text. This is the supported human-facing preparation diagnostic; raw coordinate lookup tables are intentionally absent from the persisted TOML plan.

## Migrate a saved plan

Import a supported legacy JSON plan to the current schema without rerunning
planning. `migrate` is the only CLI path that reads saved plan JSON; its output is
always canonical TOML:

```bash
utterplan migrate old.utterplan.json -o current.utterplan.toml
utterplan migrate old.utterplan.json --check
utterplan migrate old.utterplan.json > current.utterplan.toml
```

Without `-o`, TOML is written to stdout and status is written to stderr. Existing
output files are refused unless `--force` is supplied. `--check` validates the
route and reports source schema, target schema, and whether migration is required
without writing a file. A future schema version is rejected rather than guessed
or downgraded.

Schema migration is a separate operation from SSMD source migration. UtterPlan
preserves released schemas v1, v2, and v3 and migrates supported plans through the
registered chain to current schema v4. The v3-to-v4 step does not rerun parsing,
NLP, or planning. Use `ssmd migrate FILE --to 0.9` for older SSMD source
documents.

For a saved TOML plan, `validate` verifies the current semantic schema and plan
invariants; JSON plan paths are rejected outside `migrate`. For an SSMD or
plain-text source document, it runs the canonical one-document semantic compiler
without writing a plan; plain input requires `--language`, while SSMD can use its
header language or an explicit fallback.
