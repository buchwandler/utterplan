# Command-line interface

UtterPlan's command-line compiler accepts literal text, stdin, and files:

```text
usage: utterplan compile [-h] [--file FILE] --language LANGUAGE
                       [--input-format {auto,text,ssmd}]
                       [--unit {paragraph,sentence}]
                       [--text-preparation {spokenform,identity}]
                       [--pause-mode {tts,manual,auto}]
                       [--spacy {auto,off,sm,md,lg,trf}] [-o OUTPUT]
                       [--force] [--json]
                       [text ...]
```

`--lang` is an alias for `--language`. The older `--format` spelling is
accepted as an alias for `--input-format`.

## Input resolution

The rules are deterministic:

1. `--file FILE` reads exactly that UTF-8 file and cannot be combined with
   positional text.
2. With no positional text or `--file`, stdin is read. An empty terminal or
   empty stdin is an error.
3. `--input-format text` always joins positional tokens as literal text.
4. Otherwise, one positional token naming an existing regular file is read.
5. All remaining positional tokens are joined with single spaces as literal
   text.

With `auto`, only a resolved `.ssmd` file is interpreted as SSMD. Literal text
and stdin default to plain text. Use `--input-format ssmd` explicitly for
SSMD from stdin.

## Output and errors

Without `--output`, compile writes the actual pretty plan JSON to stdout. With
`--output`, the file is written and an existing file is refused unless
`--force` is supplied. Add `--json` with an output path to write the file and
also emit the same plan JSON to stdout.

Human status messages are written to stderr, never mixed into JSON stdout:

```bash
utterplan compile chapter.ssmd --lang en-us -o chapter.utterplan.json
# status is written to stderr
utterplan compile chapter.ssmd --lang en-us -o chapter.utterplan.json --json | jq .
```

Argparse usage errors use exit code 2. Input, planning, file, and plan
validation errors use exit code 1 and are reported without a traceback.

## Explain a plan

Explain an existing compiled plan as a human-readable speech narrative:

```bash
utterplan explain chapter.utterplan.json
utterplan explain chapter.utterplan.json --details
```
The default output shows the prepared wording, render units, ordered segments, languages, resolved pauses, directives, markers, and warnings. Add `--details` for IDs, offsets, provenance, hashes, plan identity, and token analysis beneath each segment. Use `inspect --tokens` for a compact token/provenance view.

## Planning controls

- `--unit paragraph|sentence` chooses render-unit grouping.
- `--text-preparation spokenform|identity` chooses written-to-spoken handling.
- `--pause-mode tts|manual|auto` selects semantic pause policy.
- `--spacy off|auto|sm|md|lg|trf` selects deterministic fallback, automatic
  spaCy use, or a required model tier.

The default spaCy policy is `off`, so the CLI does not depend on whichever optional model happens to be installed.

The complete defaults are `--text-preparation spokenform`, `--pause-mode tts`, and `--spacy off`. `spokenform` is the default text-preparation backend, while `tts` is the default pause mode. `--spacy off` uses UtterPlan's deterministic fallback tokenizer and analysis and does not require an installed spaCy model.

Use `--spacy auto` only as an opt-in enrichment policy. If a compatible local model is available, it may provide richer tokenization, POS tags, lemmas, and tags; `auto` is not the default and no model is downloaded automatically.

## Other commands

```bash
utterplan --version
utterplan validate chapter.utterplan.json
utterplan inspect chapter.utterplan.json --segment 0
utterplan inspect chapter.utterplan.json --unit 0 --boundaries --tokens
utterplan inspect chapter.utterplan.json --preparation
```

`inspect --preparation` reports the preparation backend and version, structural and spoken text lengths, replacement count, and each replacement's structural and spoken ranges and text. This is the supported human-facing preparation diagnostic; raw coordinate lookup tables are intentionally absent from plan JSON.

## Migrate a saved plan

Migrate a supported saved plan to the current schema without rerunning planning:

```bash
utterplan migrate old.utterplan.json -o current.utterplan.json
utterplan migrate old.utterplan.json --check
utterplan migrate old.utterplan.json | jq .
```

Without `-o`, migrated JSON is written to stdout. Status is written to stderr. Existing output files are refused unless `--force` is supplied. `--check` validates the route and reports source schema, target schema, and whether migration is required without writing a file. A future schema version is rejected rather than guessed or downgraded.

`validate` performs the same in-memory compatibility check and reports both source and current schema versions. It never modifies the input file.
