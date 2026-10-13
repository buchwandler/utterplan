---
schema_version: 4
id: content-0008
kind: content
type: section
section: cross_cutting_concepts
title: Cross-cutting Concepts
order: 80
status: accepted
version: 2
body_format: markdown
---

## Coordinate spaces

Every offset has a documented coordinate space (see the
[coordinate-space contract](coordinate-spaces)). Token `start`/`end` offsets are
Python-character indexes into the owning segment's `text`, never document-global
coordinates. Replacement spans are local to the final prepared segment text; full
source maps remain in the optional trace.

## Compiler-owned segmentation topology

Segmentation has four distinct layers: parser-owned paragraph events define
paragraph regions; PhraseSplit supplies advisory sentence-boundary proposals;
UtterPlan validates those proposals and owns canonical paragraph, sentence, and
private sentence-part spans in prepared spoken-text coordinates; language,
directive, authored-pause, marker, and media cuts subdivide a part into final
segments. Positive-width atomic media spans protect their interiors from automatic
sentence/part boundaries; zero-width media events remain renderer operations, not
parts. The public v7 FlowPlan contains only the resulting compact ordered
flow—there is no serialized sentence-parts table.

PhraseSplit failure or an invalid proposal batch falls back to deterministic,
conservative terminal scanning. Unsafe automatic cuts inside provider-aware lexical
content are merged or dropped before projection; the final flow-projection
token-edge check remains defense in depth. Exact surface and non-whitespace
coverage checks run before and after applicable repairs. This normalization is
independent of `renderability_mode`: strict and repair compilation use the same
topology, while renderability mode governs only the punctuation-repair policy.

## Pause and directive semantics

Authored SSMD breaks project to local `PauseIntent` values on segment edges, while
safe clause, sentence, paragraph, parenthetical, and voice-change opportunities are
carried separately as boundary kinds. Both facts may coexist at one edge. UtterPlan
does not activate automatic pauses or invent numeric durations; downstream
renderers choose native, automatic, or manual realization. Exact authored timed
breaks remain exact. Ambiguous historical pause evidence fails migration rather
than being guessed.

Typed directives are renderer-neutral values resolved from SSMD scopes and voice
defaults. Logical voice bindings remain references, not concrete engine voices.
Audio references and extension names are data only; UtterPlan does not fetch media
or execute handlers.

## Identity and determinism

Plan identity is deterministic and renderer-independent. The v7 `plan_id` includes
the exact UTF-8 SHA-256 digest of optional raw source, plus executable flow,
canonical boundary opportunities, authored pause intents, and compact portable
metadata; it never hashes TOML formatting. The v7 `utterplan-flow-v3` identity
includes boundaries, while v5/v6 retain their historical hash schemas. Renderer
chunk and pause strategies are not identity inputs. Trace data, provider documents,
model sessions, diagnostics, producer/package version, G2P output, and audio do not
define executable identity. Package version is independent of explicit plan
`schema_version`.

## Preparation and source retention

Preparation creates structural and spoken representations internally. The
executable FlowPlan retains prepared segment text and compact segment-local
replacement views, and v7 stores the exact raw input once in its optional
`PlanSource` record; it does not retain structural text or full source-to-spoken
maps, parser annotations, or global compiler token tables. Detailed diagnostics and
complete provenance mappings remain in an optional trace.

## Persistence and atomic IO

Plans persist as deterministic `.utterplan.toml` files. Writes use atomic IO
(temporary file plus replace) so interrupted operations never leave partial plan
files; the same mechanism protects batch reports and book outputs.

## Renderability policy

Safe punctuation-only repair is the default; `--renderability strict` rejects every
repair opportunity. Neither mode guesses a symbol's pronunciation or crosses
semantic blockers. Blocked planning outcomes may be reviewed through the separate
`utterplan.planning-attempt.v1` inspect-only artifact; such candidates remain
drafts and never become canonical plans.
