# UtterPlan format v6

Current plans are persisted as UTF-8 TOML in `.utterplan.toml` files. Their root fields identify `format = "utterplan"` and `schema_version = 6`. Schema v5 introduced the breaking renderer-facing contract: an ordered `flow` of render units, each containing its segments. Schema v6 retains that flow and adds optional exact-source provenance with an explicitly versioned plan hash. The canonical Python model is `FlowPlan`.

A minimal plan looks like this:

```toml
format = "utterplan"
schema_version = 6
plan_id = "sha256:..."
language = "en-us"
unit = "paragraph"
hash_schema = "utterplan-flow-v2"

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
```

## Compiler-only segmentation topology

The compiler validates PhraseSplit proposals and owns paragraph, sentence, and sentence-part spans in spoken-text coordinates. Semicolon/context-safe colon boundaries and optional clause/parenthetical proposals may create renderer cuts; language, directive, pause, marker, and media subdivisions retain the owning sentence-part identity internally. If proposals are malformed or incomplete, deterministic fallback is used and non-whitespace text remains covered exactly.

Sentence parts and their indices are deliberately absent from this v6 format. The `flow` contains only executable renderer segments and remains the compact public contract; no schema field, FlowPlan/FlowUnit/FlowSegment shape, or migration rule records private topology. Schema v5 is unchanged.

## Executable flow

Each ordered `flow` entry is a `FlowUnit` with a stable local `hash` and one or more `segment` entries. A segment contains already-prepared speech `text`, an optional language override, local token columns, optional compact replacement provenance, optional semantic `pause_before` / `pause_after` intents, typed renderer-neutral directives, markers, and an optional heading level. Language defaults to the root `language`; `unit` identifies paragraph or sentence grouping. Consumers render segments in the stored order and do not need compiler lookup tables or segment-ID joins.

Token `span` entries are half-open Python-character ranges local to their owning segment's `text`. `pos`, `tag`, `lemma`, and `morph` carry final prepared-text linguistic facts; dense columns align with spans and sparse columns use ascending `[token_index, value]` pairs. Absent lemma values derive from case-folded surface text; an explicit empty sparse lemma preserves an unknown value. These fields are the downstream context, so consumers should not retokenize or rerun spaCy.

Optional compact `replacement` columns explain text preparation without restoring the compiler graph. `replacement.span` is a list of half-open spans in the final prepared segment `text`; `replacement.source` holds the original spelling for each span. For example, in `"Because someone (A R T) thought..."`, `replacement.span = [[17, 22]]` and `replacement.source = ["ART"]`, because `segment.text[17:22] == "A R T"`. Optional `kind` and `rule` columns are sparse `[replacement_index, value]` pairs. Replacement provenance is not a synthesis input and is excluded from flow-unit hashes and `plan_id`; schema v6 separately includes the exact source digest when a source record is available. Full source offsets and preparation maps remain in the trace sidecar.
The prepared output string is not duplicated; recover it as `segment.text[start:end]`.

Pause intents represent `none`, semantic strengths such as `sentence` or `parenthetical`, or an exact authored timed break. They do not contain planner-invented durations or renderer activation policies. A consumer decides how supported semantic intents map to engine behavior; exact authored times remain explicit. Directives are typed renderer-neutral semantics for voice, pronunciation, prosody, emphasis, say-as, substitution, audio references, and extension references. UtterPlan does not fetch audio or execute extensions.

`document` holds compact `DocumentInfo` such as source format, SSMD version, title, and portable document semantics. `linguistics` optionally lists provider/model provenance. `producer` and `warnings` are informational; newly compiled v6 plans include `producer.text_preparation` with the resolved `ssmd`, `spokenform`, or `identity` mode (older migrated plans may not have it). This field is provenance, not a replayable configuration object, and does not affect plan identity. The optional v6 `source` record retains exact raw input once; it may be absent on migrated v5 plans. The executable plan does not retain compiler text-preparation objects, parser/provider documents, arbitrary global token tables, or diagnostic lookup graphs.

`plan_id` identifies canonical executable semantics and, in schema v6, the SHA-256 digest of exact raw source when available; it does not hash TOML bytes. The plan-level `hash_schema` is `utterplan-flow-v2`; flow-unit hashes remain `utterplan-unit-v3` and are computed from each unit's executable segment semantics. Compact replacement provenance is excluded. Producer identity and formatting do not alter executable identity. Plans contain no phonemes, model token IDs, models, sessions, renderer configuration, or audio.

## TOML API and optional compiler trace

`FlowPlan.to_toml()`, `FlowPlan.from_toml()`, `FlowPlan.save()`, and `FlowPlan.load()` are the persistence APIs. `save()` writes atomically. Normal plan loading and the `validate`, `inspect`, and `explain` commands accept TOML; JSON is never auto-detected as a current plan format. Import a historical JSON plan explicitly with `utterplan migrate old.utterplan.json -o current.utterplan.toml`.

Full compiler provenance is optional and separate from executable flow. `utterplan compile --trace plan.trace.toml` writes a versioned trace sidecar containing source text/hash, structural and prepared text, coordinate maps, preparation changes, compiler-only plan state, diagnostics, and renderability evidence. Schema v6 also stores exact raw input in the plan's optional source record. Compact segment-local replacement views in v6 flow are not a substitute for full source maps. Use `utterplan explain plan.utterplan.toml --trace plan.trace.toml` or `utterplan inspect-trace plan.trace.toml`. Trace data does not enter `FlowPlan`, plan identity, or plan TOML; compiling with and without a trace produces identical executable plans.

The v6 TOML codec is a deterministic human-oriented projection of `FlowPlan`, not a dump of arbitrary Python object state. Direct TOML nulls, dates/times, non-finite floats, and unknown fields are rejected. Optional typed fields are omitted; free-form `document.semantics` preserves embedded nulls with the reserved `__utterplan_null__ = true` table. The `__utterplan_` prefix is reserved. Use the public codec rather than manually reconstructing model objects.

## Historical JSON schemas and migration

Frozen JSON Schema resources for v1, v2, v3, and v4 remain under `spec/schemas/` and their versioned package copies. They describe historical serialized semantic mappings, not current TOML syntax. Schemas v5 and v6 deliberately have no JSON Schema resources or JSON plan-file format: validity is defined by their versioned `FlowPlan` models and TOML codecs. Historical files and fixtures remain versioned and immutable.

Supported historical plans migrate sequentially through v2, v3, and v4 to v5, then v6. The v1-to-v2, v2-to-v3, v3-to-v4, v4-to-v5, and v5-to-v6 steps operate on serialized plain data only. They do not parse SSMD, invoke preparation or NLP, plan, call G2P, render, or process audio. The v4-to-v5 step projects verified segments and token spans into local flow; if token ownership/coordinates or authored pause meaning cannot be established without guessing, migration fails safely. Migration preserves a compiled plan; compiling source again is a separate operation.

Package version and plan schema version are independent. Historical schema files are never rewritten to match the package. Downgrades from v6 are not supported.

## Coordinate and provenance rules

- Token `span` offsets address Python characters in the owning `FlowSegment.text` only.
- `FlowSegment.text` is the prepared speech text for that segment.
- Compiler trace source spans address exact input-source Python-character offsets; trace structural/spoken maps and preparation changes document their coordinate spaces explicitly.
- The executable plan does not contain complete source offsets or dense text maps. Compact replacement views retain only segment-local output spans and original spelling strings; preserve a trace sidecar for source diagnostics, full preparation maps, or provenance that must survive a process boundary.

The codec validates token ordering and bounds, directive shape, flow hashes, plan identity, and supported schema version before returning a `FlowPlan`. Historical model decoding remains separate from the current v6 model.
