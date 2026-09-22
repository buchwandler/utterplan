# UtterPlan format v2

A plan is UTF-8 JSON with `format: "utterplan"` and the current `schema_version: 2`. Schema v1 remains frozen at `spec/schemas/v1.schema.json` and `utterplan/schemas/v1.schema.json`. The exact caller input is retained in `source`; `texts.structural` is parsed structure and `texts.spoken` is the prepared text sent toward G2P.

The top-level semantic categories include source, config, texts, preparation, languages, `linguistic_runs`, annotations, boundaries, tokens, segments, units, markers, warnings, diagnostics, and `plan_id`. Segments are the atomic engine-facing records. Their ranges are half-open offsets into `texts.spoken`. Units group segments by paragraph or sentence.

`plan_id` is `sha256:` followed by the SHA-256 digest of canonical semantic JSON. Canonical JSON uses UTF-8, sorted keys, compact separators, no ASCII escaping, and excludes producer, warnings, diagnostics, and identity itself. Unit hashes use `utterplan-unit-v2`, include each referenced token's text, language, lemma, POS, tag, and morph, and contain no phonemes, models, embeddings, or audio.

Pauses contain both resolved seconds and contributing boundary IDs. Boundary records preserve kind, origin, strength, and position so a plan can answer why a renderer should pause. Directives are typed semantic requests for voice, pronunciation, prosody, emphasis, and external audio metadata.

The `preparation` object is compact provenance rather than working memory. It contains `backend`, nullable `version`, `languages`, `replacements`, and `warnings`. Canonical structural and spoken text remain in `texts`, so `source_text`, `spoken_text`, `offset_map`, and dense lookup arrays are not serialized. Optional token metadata may be null; inactive segment directives serialize as `{}`.
Readers reject future or unavailable schema versions rather than guessing. Supported historical versions are migrated before current-model decoding. Unknown top-level semantic fields are not accepted by the current schema. Extensions belong in documented metadata dictionaries.

## Coordinate and provenance rules

Annotations retain `structural_start` and `structural_end` in `texts.structural` plus nullable `spoken_start` and `spoken_end` in `texts.spoken`. Preparation stores backend, version, language runs, replacement provenance, and warnings. It does not serialize the transient coordinate map. Boundary and marker positions are always spoken coordinates; segment ranges and renderer-facing annotation applicability are also spoken coordinates.

Automatic parenthetical boundary positions use spoken-text coordinates. A `parenthetical_open` boundary is at the opening parenthesis and has `attrs.anchor` set to `before`. A `parenthetical_close` boundary is immediately after the closing parenthesis and also has `attrs.anchor` set to `before`, so the closing pause belongs before the resumed host segment. Detected automatic boundaries may remain in `plan.boundaries` for provenance while not affecting `segments`, `pause_before`, or `pause_after` when the active pause policy disables them.
The planner validates nested JSON shapes before constructing objects. It rejects malformed field types instead of coercing values, and validates range, ordering, reference, unit membership, hash, and plan identity invariants.

## Schema versioning and migration

Schema version 2 is the current serialized format. The package version is independent from the plan schema version. The immutable v1 definition is retained at `spec/schemas/v1.schema.json` and `utterplan/schemas/v1.schema.json`; `spec/utterplan.schema.json` and `utterplan/utterplan.schema.json` are current v2 aliases.

Every supported historical plan is routed by its declared schema version before current model construction. The v1-to-v2 migration is deterministic representation conversion over plain JSON data. It does not rerun SSMD parsing, spokenform, phrasplit, linguistic analysis, planning, G2P, or rendering. Legacy linguistic provenance is marked `unknown`; missing POS/tag values are never inferred.

`UtterancePlan.from_dict`, `from_json`, and `load` accept supported historical plans and return the current in-memory model. Future schema versions fail with `UnsupportedSchemaError`; missing backward links fail with a migration-specific path error. Downgrades are not supported.

A migration may assign a new `plan_id` because identity is canonical to the representation and schema version. When a real migration occurs, the original schema version and plan ID are retained in non-semantic `producer.migration` provenance. Migration provenance does not affect unit content hashes.

The current unit hash identifier is `utterplan-unit-v2`. It includes pronunciation-relevant token semantics but excludes token IDs, provider names, and package versions.

Released schema files and historical fixtures are immutable. A future schema release requires a new frozen schema resource, a sequential migration step, historical fixture coverage, deterministic migration evidence, current semantic validation, and package coverage for all supported schemas.
