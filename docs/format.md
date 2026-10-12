# UtterPlan format v7

Current plans are persisted as UTF-8 TOML in `.utterplan.toml` files with root `format = "utterplan"` and `schema_version = 7`. Schema v5 introduced ordered flow units; v6 added optional exact-source provenance; v7 removes renderer-selected root `unit` and adds canonical `boundary_before` / `boundary_after` opportunities distinct from authored pause intents. The canonical Python model is `FlowPlan`.

A minimal plan looks like this:

```toml
format = "utterplan"
schema_version = 7
plan_id = "sha256:..."
language = "en-us"
hash_schema = "utterplan-flow-v3"

[document]
format = "plain"
semantics = {}

[source]
format = "plain"
text = "Hello world."
sha256 = "sha256:<digest-of-exact-UTF-8-source>"

[[flow]]
hash = "sha256:..."

[[flow.segment]]
text = "Hello world."
token.span = [[0, 5], [6, 12]]
boundary_after = ["sentence"]
pause_after = "none"
```

## Compiler-only segmentation topology

The compiler validates PhraseSplit proposals and owns paragraph, sentence, and sentence-part spans in spoken-text coordinates. Semicolon/context-safe colon boundaries, optional clause/parenthetical proposals, and deterministic comma fallback may contribute safe boundary opportunities. A fallback comma is a soft `clause` opportunity only when lexical content occurs on both sides; token-edge reconciliation still applies, and candidates inside atomic replacement/media spans (or immediately after a substitution target) are suppressed. These opportunities do not activate pauses. Language, directive, authored-pause, marker, and media cuts create canonical segments without applying downstream chunk or pause policy. If proposals are malformed or incomplete, deterministic fallback is used and prepared speech text remains intact.

Sentence parts and their indices remain compiler-private in v7. The `flow` uses fixed paragraph-local `FlowUnit` grouping, and its `FlowSegment` records expose canonical safe-boundary opportunities; renderer chunk topology is not serialized. Released v5/v6 formats and their historical hashes remain unchanged.

## Executable flow

Each ordered `flow` entry is a `FlowUnit` with a stable local `hash` and one or more `segment` entries. A segment contains already-prepared speech `text`, an optional language override, local token columns, optional compact replacement provenance, optional semantic `pause_before` / `pause_after` intents, typed renderer-neutral directives, markers, and an optional heading level. Language defaults to the root `language`; units always group the canonical paragraph-local flow and the schema has no renderer-selected root `unit`. Consumers render segments in the stored order and do not need compiler lookup tables or segment-ID joins.

`boundary_before` / `boundary_after` list unique safe opportunities from `clause`, `sentence`, `paragraph`, `parenthetical`, and `voice_change` in canonical order; a parenthetical or sentence opportunity is not a pause directive. Authored pause intents are kept separately, so a boundary and an authored `none`, strength, or timed break can coexist at one edge. A `FlowSegment` is a semantic plan segment, not necessarily a renderer call or final TTS chunk.

Consumers may project saved flow into `segment`, `clause`, `sentence`, or `paragraph` preview chunks without changing schema-v7 data. The public preview concatenates each selected chunk's stored `segment.text` exactly; token and replacement spans remain local to their original segments. Pause policies are projections only and do not persist renderer timing or activate boundaries in the plan.

Token `span` entries are half-open Python-character ranges local to their owning segment's `text`. `pos`, `tag`, `lemma`, and `morph` carry final prepared-text linguistic facts; dense columns align with spans and sparse columns use ascending `[token_index, value]` pairs. Absent lemma values derive from case-folded surface text; an explicit empty sparse lemma preserves an unknown value. These fields describe linguistic tokens, not engine token IDs or model-token counts; consumers may pass the context through without retokenizing or rerunning spaCy.

Optional compact `replacement` columns explain text preparation without restoring the compiler graph. `replacement.span` is a list of half-open spans in the final prepared segment `text`; `replacement.source` holds the original spelling for each span. For example, in `"Because someone (A R T) thought..."`, `replacement.span = [[17, 22]]` and `replacement.source = ["ART"]`, because `segment.text[17:22] == "A R T"`. Optional `kind` and `rule` columns are sparse `[replacement_index, value]` pairs. Replacement provenance is not a synthesis input and is excluded from flow-unit hashes and `plan_id`; schema v7 includes the exact source digest when a source record is available. Full source offsets and preparation maps remain in the trace sidecar.
The prepared output string is not duplicated; recover it as `segment.text[start:end]`.

Pause intents represent authored `none`, strength values (`x-weak`, `weak`, `medium`, `strong`, `x-strong`), or an exact authored timed break. Safe sentence and parenthetical opportunities are boundary kinds, not pause intents. UtterPlan does not activate automatic pauses or assign durations; consumers choose native, automatic, or manual realization, and exact authored times remain explicit. Directives are typed renderer-neutral semantics for voice, pronunciation, prosody, emphasis, say-as, substitution, audio references, and extension references. UtterPlan does not fetch audio or execute extensions.

`document` holds compact `DocumentInfo` such as source format, SSMD version, title, and portable document semantics. `linguistics` optionally lists provider/model provenance. `producer` and `warnings` are informational; newly compiled v7 plans include `producer.text_preparation` with the resolved `ssmd`, `spokenform`, or `identity` mode (older migrated plans may not have it). This field is provenance, not a replayable configuration object, and does not affect plan identity. The optional v6 `source` record retains exact raw input once; it may be absent on migrated v5 plans. The executable plan does not retain compiler text-preparation objects, parser/provider documents, arbitrary global token tables, or diagnostic lookup graphs.

`plan_id` identifies canonical executable semantics and, in schema v7, the SHA-256 digest of exact raw source when available; it does not hash TOML bytes. The plan-level `hash_schema` is `utterplan-flow-v3`; canonical boundary opportunities and authored pause intents participate in executable identity and flow-unit hashes. Compact replacement provenance is excluded. Producer identity and formatting do not alter executable identity. Plans contain no phonemes, model token IDs, models, sessions, renderer configuration, or audio.

## TOML API and optional compiler trace

`FlowPlan.to_toml()`, `FlowPlan.from_toml()`, `FlowPlan.save()`, and `FlowPlan.load()` are the persistence APIs. `save()` writes atomically. Normal plan loading and the `validate`, `inspect`, and `explain` commands accept TOML; JSON is never auto-detected as a current plan format. Import a historical plan explicitly with `utterplan migrate`; schema-v6 data cannot be promoted to v7 without recompiling the original source, so migration may report `migration.recompile_required` instead of writing a file.

Full compiler provenance is optional and separate from executable flow. `utterplan compile --trace plan.trace.toml` writes a versioned trace sidecar containing source text/hash, structural and prepared text, coordinate maps, preparation changes, compiler-only plan state, diagnostics, and renderability evidence. Schema v6 also stores exact raw input in the plan's optional source record. Compact segment-local replacement views in v7 flow are not a substitute for full source maps. Use `utterplan explain plan.utterplan.toml --trace plan.trace.toml` or `utterplan inspect-trace plan.trace.toml`. Trace data does not enter `FlowPlan`, plan identity, or plan TOML; compiling with and without a trace produces identical executable plans.

The v7 TOML codec is a deterministic human-oriented projection of `FlowPlan`, not a dump of arbitrary Python object state. Direct TOML nulls, dates/times, non-finite floats, and unknown fields are rejected. Optional typed fields are omitted; free-form `document.semantics` preserves embedded nulls with the reserved `__utterplan_null__ = true` table. The `__utterplan_` prefix is reserved. Use the public codec rather than manually reconstructing model objects.

## Historical JSON schemas and migration

Frozen JSON Schema resources for v1, v2, v3, and v4 remain under `spec/schemas/` and their versioned package copies. They describe historical serialized semantic mappings, not current TOML syntax. Schemas v5, v6, and v7 deliberately have no JSON Schema resources or JSON plan-file format: validity is defined by their versioned `FlowPlan` models and TOML codecs. Historical files and fixtures remain versioned and immutable.

Historical plans retain sequential data-only migration steps from v1 through v6. The registered v6-to-v7 step refuses with `migration.recompile_required`, because v6 may omit renderer-dependent automatic boundaries. Earlier steps operate on serialized plain data only and never parse SSMD, invoke preparation or NLP, plan, call G2P, render, or process audio. The v4-to-v5 step verifies token ownership/coordinates and authored pause meaning rather than guessing; v5-to-v6 preserves compiled semantics without inventing source provenance. Recompile the original source to obtain a complete v7 boundary inventory.

Package version and plan schema version are independent. Historical schema files are never rewritten to match the package. Downgrades from v7 are not supported.

## Coordinate and provenance rules

- Token `span` offsets address Python characters in the owning `FlowSegment.text` only.
- `FlowSegment.text` is the prepared speech text for that segment.
- Compiler trace source spans address exact input-source Python-character offsets; trace structural/spoken maps and preparation changes document their coordinate spaces explicitly.
- The executable plan does not contain complete source offsets or dense text maps. Compact replacement views retain only segment-local output spans and original spelling strings; preserve a trace sidecar for source diagnostics, full preparation maps, or provenance that must survive a process boundary.

The codec validates token ordering and bounds, directive shape, flow hashes, plan identity, and supported schema version before returning a `FlowPlan`. Historical model decoding remains separate from the current v7 model.
