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

## Produce or replan a RenderPlan

`render-plan` accepts only the current schema-v7 `.utterplan.toml` file and a
`RenderProfile` TOML file. It does not re-prepare text, infer semantic boundaries,
call a renderer, or calculate backend model-token counts:

```bash
utterplan render-plan chapter.utterplan.toml \\
  --profile voice.renderprofile.toml \\
  --output chapter.renderplan.toml
```

Replanning requires both the exact previous RenderPlan and its matching preflight
report. Only failed speech occurrences are refined; successful partitions remain:

```bash
utterplan render-plan chapter.utterplan.toml \\
  --profile voice.renderprofile.toml \\
  --previous chapter.renderplan.toml \\
  --preflight chapter.preflight.toml \\
  --output chapter.next.renderplan.toml \\
  --explain
```

`--previous` and `--preflight` must be supplied together. Existing output files
require `--force`. `--explain` formats the generated plan and replan decisions; it
does not invoke planning a second time. `--json` emits a versioned JSON wrapper to
stdout while the RenderPlan artifact remains TOML at `--output`.

## Logical roles and complete-profile coverage

Role coverage is validated before grouping or replanning. The selected profile must contain every explicit speech role and, when any speech omits a role reference, its `default_role`. Missing roles are reported together as `renderplan.role.missing`; extra profile roles are allowed. The check is renderer-independent and does not add role data to the RenderPlan schema.

Use source-only role inspection without loading a RenderProfile:

```bash
utterplan inspect chapter.utterplan.toml --roles
```

The human `render-plan` summary reports required roles and `coverage: complete`. With `--json`, the versioned CLI wrapper includes a `role_coverage` object (`default_role`, `required`, `available`, `missing`, and `uses_default_role`) alongside, but outside, the RenderPlan payload.

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

Compile reports use format version 2. Each successful item records its resolved `preparation_mode`, diagnostic/severity counts, a complete structured `diagnostics` list, `renderability_repair_count`, and a `degraded_linguistics` boolean. For compatibility, `repair_count` and `repairs` remain; they include segmentation diagnostics (including informational ones) as well as renderability repairs, so they are not the terminal warning/repair summary. Diagnostic source ranges use original-input Python-character coordinates where available. Failed or skipped items have no preparation result. Reports remain operational metadata and do not affect plan output or incremental write behavior.

Shared planning options include `--language`, `--input-format auto|plain|ssmd`, `--text-preparation`, `--spacy`, and `--renderability`. `--diagnostics warnings|all|none` controls terminal detail (default `warnings`): warnings mode suppresses informational diagnostics, all includes them, and none suppresses non-failure diagnostics. Failures are always reported, and the operational report always retains complete diagnostics. Progress, selected diagnostic details, actionable errors, and final counts are written to stderr. Exit status is 0 if every input succeeds, 1 if any input fails, and 2 for usage errors such as output collisions. `--fail-fast` skips later requests after the first failure but preserves all completed outputs and updates the report.

## Compile one SSMDDoc workspace

`compile-document` reads a single editable `ssmdconvert.document` v1 workspace and compiles its canonical SSMD 0.9 document into one plan. It accepts the workspace root or its canonical `document.ssmd.md` path:

```text
utterplan compile-document INPUT [--output-dir PATH] [--language LANGUAGE]
  [--text-preparation {auto,ssmd,spokenform,identity}]
  [--renderability {strict,repair}] [--spacy {auto,off,sm,md,lg,trf}]
  [--force] [--report PATH] [--diagnostics {warnings,all,none}]
```

The default output directory is `<workspace>/utterplan/`, containing `document.utterplan.toml` and `compile-report.toml`. `--output-dir` and `--report` override those locations. Existing plan files require `--force`; output collisions with the source or manifest are rejected. A document header's language is authoritative; `--language`/`--lang` is a fallback when it is absent.

Editable content wins over the stored manifest digest: compilation reads the current `document.ssmd.md` but never modifies the manifest or source. The command has no `--input-format`, chapter selection, or `--fail-fast`; it handles one document. The existing `compile` and `validate` commands also accept the workspace root or canonical document path, while `compile` retains its normal stdout/`-o` behavior. This is not `compile-book`: an SSMDDoc creates one plan, while an SSMDBook orchestrates independent chapter plans. ZIP bundles are not supported and `ssmdconvert` is not a runtime dependency. See the [SSMDDoc guide](ssmdoc.md) for format validation and the `compile_ssmdoc()` Python API.

## Project an SSMDDoc RenderPlan

`render-document` projects the already-saved single-document UtterPlan through an explicit RenderProfile. It never compiles implicitly:

```text
utterplan render-document INPUT --profile PROFILE
  [--utterplan-dir PATH] [--output-root PATH] [--variant LABEL]
  [--force] [--report PATH]
```

By default it reads `<workspace>/utterplan/document.utterplan.toml` and writes a profile-fingerprinted variant under `<workspace>/renderplan/<label>--<profile-id-prefix>/`, containing `renderprofile.toml`, `document.renderplan.toml`, and `render-report.toml`. `--variant` changes only the readable label; the profile fingerprint remains part of the directory identity. A profile mismatch or ambiguous existing snapshot is rejected even with `--force`. This is a one-document projection, not a book-set workflow. See the [SSMDDoc guide](ssmdoc.md).

The start summary also lists the document's required roles and coverage. Coverage is checked before a new variant directory, profile snapshot, or RenderPlan is written; a missing role leaves no partial variant.

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

Shared planning options are `--language`/`--lang`, `--text-preparation`, `--renderability`, `--spacy`, and `--diagnostics warnings|all|none` (default `warnings`). The diagnostics option controls terminal verbosity; failures are always reported, and the operational report retains all diagnostic details. Chapter documents are SSMD 0.9 by contract, so `compile-book` does not accept `--input-format`. The manifest is read-only: edited chapter content is compiled as it currently exists even if its recorded digest is stale, and UtterPlan never refreshes the manifest or chapter hashes. Only selected chapter files are opened, so an unrelated broken chapter outside the selection does not block the request.

The version-2 compile report identifies each successful chapter's resolved preparation mode (`ssmd`, `spokenform`, or `identity`), includes complete diagnostics and severity counts, a `renderability_repair_count`, and a `degraded_linguistics` flag. Compatibility fields `repair_count` and `repairs` still include segmentation diagnostics regardless of severity; use the diagnostic severity fields and `diagnostics` list for interpretation. The report is operational metadata; partial-success, atomic per-plan writes, and manifest immutability are unchanged.

For the full editable-workspace behavior and examples, see the [SSMDBook guide](ssmdbook.md).

## Produce RenderPlans for selected SSMDBook chapters

`render-plan` remains the low-level one-file projection and replan command.
`render-book` is the batch convenience workflow: it loads existing schema-v7
UtterPlans for selected manifest chapters and writes one RenderPlan per chapter
for a shared RenderProfile.

All ordinary load, validation, inspection, explanation, preview, and RenderPlan commands accept schema v7 only. Older plans fail with `schema.version_unsupported` and the guidance `This build accepts UtterPlan schema 7 only. Recompile the source with the current UtterPlan.` Use `utterplan migrate` only for the explicit serialized-data migration path; it is not invoked implicitly by normal loading.

```text
utterplan render-book INPUT --profile PROFILE [--chapters SELECTOR]
  [--utterplan-dir PATH] [--output-root PATH] [--variant LABEL]
  [--force] [--fail-fast] [--report PATH]
```

`INPUT` is an SSMDBook root containing `manifest.json` or its canonical
`chapters/` directory. `--chapters` uses the same manifest `source_number`
selector as `compile-book`: `all` (default), one number, an inclusive range, or
comma-separated selections such as `1,3-5,9`. Chapters remain in manifest order.
`--profile` is required and is loaded once through the shared RenderPlan codec; UtterPlan does not call VoiceRender or probe engines.

Before initializing a new variant, `render-book` checks role coverage across all readable selected chapter plans. A single incomplete chapter fails the projection with the missing role names and affected chapter IDs; no new profile snapshot or `renderplan-set.toml` is written. The start summary lists the aggregate required roles and complete coverage. Other missing/invalid source-plan behavior is unchanged.

Defaults and behavior:

- `--utterplan-dir`: `<book-root>/utterplan`; it must already exist. A missing
  selected plan is an item failure, not a shared configuration error.
- `--output-root`: `<book-root>/renderplan`. The command appends a profile
  variant directory named `<label>--<profile-id-prefix>`; it is not an output
  directory override for individual files.
- `--variant`: optional safe human-readable label. By default, the label comes
  from the profile filename (`narration.renderprofile.toml` becomes `narration`);
  the 12-hex-character fingerprint is always appended.
- `--force`: replace selected existing RenderPlan files only. It does not bypass
  profile-ID mismatches, invalid set metadata, unsafe paths, or collisions.
- `--fail-fast`: after the first item failure, later selected chapters are
  recorded as skipped. Otherwise, processing continues.
- `--report`: override the per-invocation `render-report.toml` location.

Each variant contains a canonical `renderprofile.toml` snapshot,
`renderplan-set.toml` collection index, latest-invocation `render-report.toml`,
and one `.renderplan.toml` file per successful chapter. The set index stores the
full canonical `profile_id`, source profile location, and source/render plan IDs.
Repeated invocations with the same profile reuse the variant and upsert entries
without removing other successful chapters; a different profile identity selects
a different default variant. UtterPlan refuses to adopt a non-empty directory
without a valid set or to reuse a missing/mismatched snapshot.

The command does not read chapter content or modify the source manifest, chapter
files, or UtterPlans. Unsafe output roots inside `chapters/`, input/output or
metadata collisions, duplicate basenames, and invalid shared profile/set state
are rejected before chapter processing. Exit status is 0 when all selected
chapters succeed, 1 when any chapter fails, and 2 for usage or shared-configuration
errors. See the [SSMDBook workflow guide](ssmdbook.md) for end-to-end and multi-voice examples.

## Replan active RenderPlans for selected chapters

`replan-book` is the book/variant orchestration for VoiceRender's capacity feedback.
It loads the profile snapshot owned by the existing RenderPlanSet; callers must select
the exact variant directory, not supply another profile:

VoiceRender supplies capacity feedback: UtterPlan does not add renderer-specific
metrics, a splitter, engine selection, synthesis, or audio composition.

```text
utterplan replan-book INPUT --variant VARIANT [--chapters SELECTOR]
  [--renderplan-root PATH] [--voicerender-root PATH] [--report PATH]
  [--dry-run] [--fail-fast] [--explain] [--json]
```

Example repeatable lifecycle:

```bash
# Initial projection and exact renderer preflight/render
utterplan render-book . --profile narration4.renderprofile.toml --variant narration4 --chapters 5
voicerender render-book . --variant narration4--28f616b6fe3b --chapters 5 \
  --emphasis-policy defer-to-compose

# If VoiceRender returns preflight.replan, refine only the active chapter plan
utterplan replan-book . --variant narration4--28f616b6fe3b --chapters 5

# Preflight/render the new active plan; repeat replan-book and this command if needed
voicerender render-book . --variant narration4--28f616b6fe3b --chapters 5 \
  --emphasis-policy defer-to-compose
```

`INPUT` is an SSMDBook root or its canonical `chapters/` directory. Chapter selectors
use manifest source numbers and retain manifest order. The default RenderPlan root is
`<book-root>/renderplan`; the default VoiceRender root is `<book-root>/voicerender`.
The command reads `<variant>/renderprofile.toml` and the selected active plan paths
from `renderplan-set.toml`. It discovers reports under
`<voicerender-root>/<variant>/<chapter-id>/`, preferring `preflight-recheck.toml`
over `preflight.toml` when both fully validate against the exact active RenderPlan.

Only a matching `status="replan"` report is accepted. Missing reports, stale parent
reports, mismatched profile/plan identities, and `ok`/`reject` statuses fail that
chapter; the command never falls back to an initial RenderPlan projection. A successful
replan writes a deterministic immutable child plan first, then atomically changes only
the selected chapter's active set entry. Parent plans, source UtterPlans, profile
identity, and unselected set entries remain unchanged. Run VoiceRender again after
each replan; repeat the two feedback steps until preflight is `ok`.

Defaults and behavior:

- `--variant` is required and must name the existing full variant directory, including
  its profile fingerprint. The profile snapshot is loaded from that collection.
- `--chapters`: `all`, one source number, an inclusive range, or comma-separated
  selections; default is `all`.
- `--renderplan-root` and `--voicerender-root` override the collection/data roots,
  not the selected variant or chapter paths recorded by the contracts.
- `--report`: defaults to `<variant-dir>/replan-report.toml`; progress is persisted
  after each chapter and the final report is marked complete.
- `--dry-run`: validates and plans children without writing child RenderPlans or
  changing the set index. It writes the operational report and reports successful
  items as `planned`.
- `--fail-fast`: later chapters are recorded as skipped after the first failure;
  without it, later selected chapters continue.
- `--explain` uses the existing per-request RenderPlan explanation; `--json` emits
  structured outcome paths, identities, replacement counts, errors, and optional
  explanations.

Re-running with a stale report after activating a child fails with
`renderplan.replan.book.preflight_stale`. VoiceRender must first measure the active
child to produce its own matching feedback report.

## Explain a plan

Explain an existing compiled plan as a human-readable speech narrative:

```bash
utterplan explain chapter.utterplan.toml
utterplan explain chapter.utterplan.toml --details
```

The explanation presents executable flow: prepared segment text, paragraph-local unit order, effective languages, canonical boundary opportunities, authored pause intents, headings, markers, and typed directives. The v7 plan retains exact raw source when available and compact replacement views show local prepared surfaces with original spellings. Complete compiler source diagnostics and preparation maps remain absent unless a trace sidecar was saved. Add `--details` for local token offsets, flow hashes, plan identity, and trace preparation mappings. Pass `--trace PATH` to attach a matching sidecar; the TOML trace can also be read independently with `inspect-trace`.

## Preview a saved consumer plan

`preview` projects chunk text and pause facts from a saved schema-v7 plan. It does not recompile the source, call linguistics providers, modify the plan, or cross into G2P/rendering:

```bash
utterplan preview chapter.utterplan.toml \
  --segments 58-62 \
  --chunk-by clause \
  --pause-policy automatic
```

`--segments` accepts zero-based global flow-segment indexes: `N`, `N-M`, comma-separated combinations, or `all`. It is a focus selector: grouping is performed for the full plan first, so selecting one segment returns its complete containing chunk. `--chunk-by` is `segment`, `clause`, `sentence` (default), or `paragraph`; clause grouping closes on clause, sentence, and paragraph opportunities. Chunk text is the exact concatenation of stored `segment.text` values, including spaces at chunk edges.

`--pause-policy native` (default) shows authored pause intent but does not materialize ordinary boundary opportunities. `automatic` exposes saved clause/sentence/paragraph opportunities without inventing durations. `manual` displays authored pause intent and the automatic opportunity separately. These policies affect preview projection only; the saved plan and its identity remain unchanged. Use `--details` to show constituent segments, local spans, directives, and boundary facts, or `--json` for the versioned machine-readable preview object.

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
utterplan preview chapter.utterplan.toml --segments 58-62 --chunk-by clause --pause-policy automatic
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
