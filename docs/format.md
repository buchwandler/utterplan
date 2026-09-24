# UtterPlan format v3

A plan is UTF-8 JSON with `format: "utterplan"` and the current `schema_version: 3`. Schemas v1 and v2 are frozen at their versioned paths under `spec/schemas/` and `utterplan/schemas/`. The exact caller input is retained in `source`; `texts.structural` is parsed structure and `texts.spoken` is the prepared text sent toward G2P.

The top-level semantic categories include source, config, texts, preparation, languages, `linguistic_runs`, `document_metadata`, annotations, boundaries, tokens, segments, units, markers, warnings, diagnostics, and `plan_id`. `document_metadata` preserves SSMD header values, including the parsed version. Boundaries preserve structural events such as headings. Segments are the atomic renderer-facing records. Their ranges are half-open offsets into `texts.spoken`. Units group segments by paragraph or sentence.

`plan_id` is `sha256:` followed by the SHA-256 digest of canonical semantic JSON. Canonical JSON uses UTF-8, sorted keys, compact separators, no ASCII escaping, and excludes producer, warnings, diagnostics, and identity itself. Unit hashes use `utterplan-unit-v2`, include each referenced token's text, language, lemma, POS, tag, and morph, and contain no phonemes, models, embeddings, or audio.

Pauses contain both resolved seconds and contributing boundary IDs. Boundary records preserve kind, origin, strength, position, and source attributes. Directives are typed renderer-neutral semantics for voice, pronunciation, effective prosody, emphasis, say-as, substitution, audio references, and extension references. Directive resolution does not invoke a renderer, fetch audio, or execute extensions.

The `preparation` object is compact provenance rather than working memory. It contains `backend`, nullable `version`, `languages`, `replacements`, and `warnings`. Canonical structural and spoken text remain in `texts`, so `source_text`, `spoken_text`, `offset_map`, and dense lookup arrays are not serialized. Optional token metadata may be null; inactive segment directives serialize as `{}`. Readers reject future or unavailable schema versions rather than guessing. Unknown top-level semantic fields are not accepted by the current schema. Extensions belong in documented metadata dictionaries.

## Coordinate and provenance rules

Annotations retain `structural_start` and `structural_end` in `texts.structural`, nullable `spoken_start` and `spoken_end` in `texts.spoken`, and nullable `source_start`, `source_end`, and `source_node_id` provenance for SSMD source nodes. Source offsets are half-open Python string offsets measured in Unicode code points into the exact original input, including header and markup. They are not renderer slicing coordinates. Diagnostic source offsets use the same coordinate space; diagnostic line and column are 1-based. Preparation stores backend, version, language runs, replacement provenance, and warnings. It does not serialize the transient coordinate map. Boundary and marker positions are always spoken coordinates; segment ranges and renderer-facing annotation applicability are also spoken coordinates.

Automatic parenthetical boundary positions use spoken-text coordinates. A `parenthetical_open` boundary is at the opening parenthesis and has `attrs.anchor` set to `before`. A `parenthetical_close` boundary is immediately after the closing parenthesis and also has `attrs.anchor` set to `before`, so the closing pause belongs before the resumed host segment. Detected automatic boundaries may remain in `plan.boundaries` for provenance while not affecting `segments`, `pause_before`, or `pause_after` when the active pause policy disables them.
The planner validates nested JSON shapes before constructing objects. It rejects malformed field types instead of coercing values, and validates range, ordering, reference, unit membership, hash, and plan identity invariants.

## Schema versioning and migration

Schema version 3 is the current serialized format. The package version is independent from the plan schema version. Immutable definitions for v1, v2, and v3 are retained under `spec/schemas/` and `utterplan/schemas/`. `spec/utterplan.schema.json` and `utterplan/utterplan.schema.json` are current schema v3 aliases.

Every supported historical plan is routed by its declared schema version before current-model construction. The v1-to-v2 and v2-to-v3 migrations are deterministic representation conversions over plain JSON data; v1 plans migrate sequentially through v2. They do not rerun SSMD parsing, spokenform, phrasplit, linguistic analysis, planning, G2P, or rendering. Legacy linguistic provenance remains `unknown`; missing POS/tag values are never inferred.

`UtterancePlan.from_dict`, `from_json`, and `load` accept supported historical plans and return the current in-memory model. Future schema versions fail with `UnsupportedSchemaError`; missing backward links fail with a migration-specific path error. Downgrades are not supported.

A migration may assign a new `plan_id` because identity is canonical to the representation and schema version. When a real migration occurs, the original schema version and plan ID are retained in non-semantic `producer.migration` provenance. Migration provenance does not affect unit content hashes.

The current unit hash identifier is `utterplan-unit-v2`. It includes pronunciation-relevant token semantics but excludes token IDs, provider names, and package versions.

Released schema files and historical fixtures are immutable. A future schema release requires a new frozen schema resource, a sequential migration step, historical fixture coverage, deterministic migration evidence, current semantic validation, and package coverage for all supported schemas.
