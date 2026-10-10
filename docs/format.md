# UtterPlan format v5

Current plans are persisted as UTF-8 TOML in `.utterplan.toml` files. Their root fields identify `format = "utterplan"` and `schema_version = 5`. Schema v5 is the breaking, renderer-facing contract: the executable plan is an ordered `flow` of render units, each containing the segments that belong to it. The canonical Python model is `FlowPlan`.

A minimal plan looks like this:

```toml
format = "utterplan"
schema_version = 5
plan_id = "sha256:..."
language = "en-us"
unit = "paragraph"
hash_schema = "utterplan-flow-v1"

[document]
format = "plain"
semantics = {}

[[flow]]
hash = "sha256:..."

[[flow.segment]]
text = "Hello world."
token.span = [[0, 5], [6, 12]]
```

## Compiler-only segmentation topology

The compiler validates PhraseSplit proposals and owns paragraph, sentence, and sentence-part spans in spoken-text coordinates. Semicolon/context-safe colon boundaries and optional clause/parenthetical proposals may create renderer cuts; language, directive, pause, marker, and media subdivisions retain the owning sentence-part identity internally. If proposals are malformed or incomplete, deterministic fallback is used and non-whitespace text remains covered exactly.

Sentence parts and their indices are deliberately absent from this v5 format. The `flow` contains only executable renderer segments and remains the compact public contract; no schema field, FlowPlan/FlowUnit/FlowSegment shape, or migration rule records private topology. Schema v5 is unchanged.

## Executable flow

Each ordered `flow` entry is a `FlowUnit` with a stable local `hash` and one or more `segment` entries. A segment contains already-prepared speech `text`, an optional language override, local token columns, optional semantic `pause_before` / `pause_after` intents, typed renderer-neutral directives, markers, and an optional heading level. Language defaults to the root `language`; `unit` identifies paragraph or sentence grouping. Consumers render segments in the stored order and do not need compiler lookup tables or segment-ID joins.

Token `span` entries are half-open Python-character ranges local to their owning segment's `text`. `pos`, `tag`, `lemma`, and `morph` columns carry token facts. Dense columns align with the spans; sparse columns are ascending `[token_index, value]` pairs. Absent lemma entries derive from case-folded surface text, while an explicit empty sparse lemma preserves an unknown value. Tokens and their semantics are never indexed by plan-global token IDs.

Pause intents represent `none`, semantic strengths such as `sentence` or `parenthetical`, or an exact authored timed break. They do not contain planner-invented durations or renderer activation policies. A consumer decides how supported semantic intents map to engine behavior; exact authored times remain explicit. Directives are typed renderer-neutral semantics for voice, pronunciation, prosody, emphasis, say-as, substitution, audio references, and extension references. UtterPlan does not fetch audio or execute extensions.

`document` holds compact `DocumentInfo` such as source format, SSMD version, title, and portable document semantics. `linguistics` optionally lists provider/model provenance. `producer` and `warnings` are informational. The executable plan does not retain the original source document, compiler text-preparation objects, parser/provider documents, arbitrary global token tables, or diagnostic lookup graphs.

`plan_id` identifies canonical executable semantics, not TOML bytes. Flow-unit hashes use the `utterplan-flow-v1` contract and are computed from each unit's local segments. Producer identity and formatting do not alter executable identity. Plans contain no phonemes, model token IDs, models, sessions, renderer configuration, or audio.

## TOML API and optional compiler trace

`FlowPlan.to_toml()`, `FlowPlan.from_toml()`, `FlowPlan.save()`, and `FlowPlan.load()` are the persistence APIs. `save()` writes atomically. Normal plan loading and the `validate`, `inspect`, and `explain` commands accept TOML; JSON is never auto-detected as a current plan format. Import a historical JSON plan explicitly with `utterplan migrate old.utterplan.json -o current.utterplan.toml`.

Compiler provenance is optional and separate from executable flow. `utterplan compile --trace plan.trace.toml` writes a versioned trace sidecar containing source text/hash, structural and prepared text, coordinate maps, preparation changes, compiler-only plan state, diagnostics, and renderability evidence. Use `utterplan explain plan.utterplan.toml --trace plan.trace.toml` or `utterplan inspect-trace plan.trace.toml`. Trace data does not enter `FlowPlan`, plan identity, or plan TOML; compiling with and without a trace produces identical executable plans.

The v5 TOML codec is a deterministic human-oriented projection of `FlowPlan`, not a dump of arbitrary Python object state. Direct TOML nulls, dates/times, non-finite floats, and unknown fields are rejected. Optional typed fields are omitted; free-form `document.semantics` preserves embedded nulls with the reserved `__utterplan_null__ = true` table. The `__utterplan_` prefix is reserved. Use the public codec rather than manually reconstructing model objects.

## Historical JSON schemas and migration

Frozen JSON Schema resources for v1, v2, v3, and v4 remain under `spec/schemas/` and their versioned package copies. They describe historical serialized semantic mappings, not current TOML syntax. Schema v5 deliberately has no JSON Schema resource or JSON plan-file format: v5 validity is defined by its `FlowPlan` model and TOML codec. Historical files and fixtures remain versioned and immutable.

Supported historical plans migrate sequentially through v2, v3, and v4 to v5. The v1-to-v2, v2-to-v3, v3-to-v4, and v4-to-v5 steps operate on serialized plain data only. They do not parse SSMD, invoke preparation or NLP, plan, call G2P, render, or process audio. The v4-to-v5 step projects verified segments and token spans into local flow; if token ownership/coordinates or authored pause meaning cannot be established without guessing, migration fails safely. Migration preserves a compiled plan; compiling source again is a separate operation.

Package version and plan schema version are independent. Historical schema files are never rewritten to match the package. Downgrades from v5 are not supported.

## Coordinate and provenance rules

- Token `span` offsets address Python characters in the owning `FlowSegment.text` only.
- `FlowSegment.text` is the prepared speech text for that segment.
- Compiler trace source spans address exact input-source Python-character offsets; trace structural/spoken maps and preparation changes document their coordinate spaces explicitly.
- The executable plan does not contain source offsets or dense text maps. Preserve a trace sidecar when source diagnostics or preparation provenance must survive a process boundary.

The codec validates token ordering and bounds, directive shape, flow hashes, plan identity, and supported schema version before returning a `FlowPlan`. Historical model decoding remains separate from the current v5 model.
