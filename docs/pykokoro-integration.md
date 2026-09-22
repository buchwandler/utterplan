# PyKokoro integration boundary

UtterPlan is an independent planning compiler. PyKokoro is an optional consumer,
not a runtime dependency of this package.
The intended migration keeps the existing PyKokoro user API unchanged:

```text
KokoroPipeline.run(text)
    -> map PipelineConfig and GenerationConfig to PlannerConfig
    -> UtterancePlanner.plan(text)
    -> adapt public PlanSegment records to PyKokoro's G2P input
    -> PyKokoro G2P
    -> phoneme processing
    -> model inference
    -> audio
```

PyKokoro owns model selection, voice assets, G2P, model tokens, ONNX sessions,
acoustic behavior, audio, and any compatibility behavior specific to its
renderer. UtterPlan owns deterministic document parsing, language planning,
written-to-spoken preparation, segmentation, semantic directives, boundaries,
pauses, markers, and render units.

## Thin adapter inputs

A future adapter can use only public UtterancePlan fields:

- `plan.texts.spoken`;
- `plan.languages`;
- `plan.tokens` and `plan.annotations`;
- `plan.boundaries`;
- `plan.segments` and `plan.units`;
- `plan.markers`;
- `plan.document_metadata`;
- resolved segment pauses and typed directives.

It should pass `PlanSegment.text` and `PlanSegment.language` to the next

For contextual pronunciation, pass the segment token snapshot to G2P:

```python
segment_tokens = plan.tokens_for_segment(segment)
if linguistic_run.provider != "spacy":
    # Fail clearly or use the consumer's documented non-contextual fallback.
    ...
phonemizer(segment.text, segment.language, segment_tokens)
```

The renderer must not rerun spaCy or infer missing POS/tag values.
frontend stage. No JSON serialization is required for in-process use.

## Pause behavior

UtterPlan resolves deterministic base semantic pauses. PyKokoro may apply
renderer or acoustic variance after consuming the plan when legacy behavior
requires it. Such variance must remain outside semantic plan identity and must
not be added to UtterPlan merely to mirror renderer settings.

## Compatibility ownership

Consumer-specific compatibility and integration tests belong in the PyKokoro
repository. UtterPlan's own test suite validates the public semantic planning
contract using repository-owned fixtures and goldens only.
