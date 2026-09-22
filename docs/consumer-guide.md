# Renderer consumer guide

UtterPlan ends at a semantic planning boundary. A renderer consumes the public
plan object and begins G2P after planning. It does not need a JSON round trip
when planner and renderer run in the same process.

## Planning defaults

UtterPlan's default text-preparation backend is `spokenform`, its default pause mode is `tts`, and the default CLI linguistic-resource policy is `spacy off`. The default path uses deterministic fallback tokenization and analysis and does not depend on an installed spaCy model.

`spacy auto` is an opt-in enrichment policy. When a compatible local model is available, it may expose richer tokenization, POS tags, lemmas, and tags. Consumers should not assume `auto` is enabled, and provider documents remain internal planning state rather than public plan data.

## Consumer contract

Use these public fields:

- `plan.texts.spoken` is the prepared text sent toward G2P.
- `segment.text` is exactly the slice of spoken text from
  `segment.spoken_start:segment.spoken_end`.
- `segment.language` identifies the language for the segment.
- `plan.languages` provides language runs.
- `plan.annotations` and `segment.annotation_ids` provide semantic spans.
- `plan.tokens` and `segment.token_indices` provide linguistic token metadata.
- `plan.boundaries` explains semantic boundary events.
- `segment.pause_before` and `segment.pause_after` are already-resolved pauses.
- `segment.directives` contains typed semantic intent, such as a logical voice
  reference or prosody request.
- `plan.markers` and `unit.marker_ids` identify marker ownership.
- `plan.units` groups segments for paragraph or sentence rendering.
- `plan.document_metadata` contains document-level metadata such as logical
  voice bindings.
Consumers may rely on these plan-level fields: `texts.spoken`, `preparation`, `languages`, `linguistic_runs`, `tokens`, `annotations`, `boundaries`, `segments`, `units`, `markers`, and `document_metadata`. Each segment additionally provides its ID, spoken text range, language, paragraph/sentence/clause ownership, resolved pauses, typed directives, token indices, and annotation IDs.

`TokenAnnotation` stores the exact spoken slice plus normalized language, lemma, coarse POS, fine-grained tag, and compact morphology. `LinguisticRun` records actual provider/model provenance.

`plan.linguistic_runs` records the actual final pass-B analysis for each language run. `provider` is `spacy`, `fallback`, or `unknown`; model and version fields are provenance, not renderer inputs. A contextual G2P consumer should use `plan.tokens_for_segment(segment)` (or `segment.token_indices`) and must explicitly fail or use a documented fallback when the relevant provider is not `spacy`.
All segment ranges and renderer-facing ranges are spoken-text coordinates.

Preparation provenance is diagnostic metadata for consumers. Do not depend on a serialized coordinate map. All structural-to-spoken conversion has already been resolved by the planner.
Voice bindings are logical names, not backend voice IDs. Consumers must not
recompute pause policy, resolve engine voices in UtterPlan, or depend on provider
documents that were used during planning.

## Stable renderer input view

Consumers may rely on these plan-level fields: `texts.spoken`, `preparation`, `languages`, `tokens`, `annotations`, `boundaries`, `segments`, `units`, `markers`, and `document_metadata`. Each segment additionally provides its ID, spoken text range, language, paragraph/sentence/clause ownership, resolved pauses, typed directives, token indices, and annotation IDs.

A completed plan is immutable consumer input. Consumers may inspect and adapt the data for G2P or rendering, but must not rewrite planning decisions or mutate the plan. The canonical invariant is:

```python
before = plan.to_json(indent=None)
plan_id = plan.plan_id
consume_plan(plan)
assert plan.to_json(indent=None) == before
assert plan.plan_id == plan_id
```

This contract does not require provider documents, models, phonemes, model token IDs, or audio to remain available after planning.

## Renderer-neutral pseudocode

```python
plan = planner.plan(source_text)

for unit in plan.units:
    for segment_id in unit.segment_ids:
        segment = next(item for item in plan.segments if item.id == segment_id)
        prepared_text = segment.text
        language = segment.language
        segment_tokens = plan.tokens_for_segment(segment)
        # Pass segment_tokens to contextual G2P without rerunning spaCy.
        pause_before = segment.pause_before.seconds
        pause_after = segment.pause_after.seconds
        # G2P and backend-specific rendering start here.
```

A consumer may instead index segments, tokens, annotations, and markers by
public IDs. The plan's own `validate()` method and `UtterancePlan.load()` enforce
reference, range, membership, identity, and unit-hash invariants.

## What is intentionally absent

Plans contain no phonemes, model token IDs, model sessions, audio, renderer
configuration, or model-derived timings. Acoustic retries and renderer-level
randomness remain outside UtterPlan.
