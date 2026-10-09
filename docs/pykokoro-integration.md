# PyKokoro integration boundary

UtterPlan is an independent planning compiler. PyKokoro is an optional consumer, not a runtime dependency of this package. A thin adapter can preserve the existing PyKokoro user API:

```text
KokoroPipeline.run(text)
    -> map PipelineConfig and GenerationConfig to PlannerConfig
    -> UtterancePlanner.plan(text)
    -> adapt public FlowPlan segments to PyKokoro's G2P input
    -> PyKokoro G2P
    -> phoneme processing
    -> model inference
    -> audio
```

PyKokoro owns model selection, voice assets, G2P, model tokens, ONNX sessions, acoustic behavior, and audio. UtterPlan owns deterministic document parsing, language planning, written-to-spoken preparation, segmentation, typed directives, semantic pause intent, markers, and render units.

## Thin adapter inputs

A future adapter can use only public v5 flow fields:

- `plan.flow` in order, with each unit's ordered `segments`;
- `segment.text` and `segment.language`;
- local `segment.tokens` for optional linguistic context;
- `segment.directives`, `pause_before`, and `pause_after`;
- `segment.markers` and optional `segment.heading`;
- compact `plan.document` and `plan.linguistics` metadata.

Token offsets are local to the owning `segment.text`. A consumer must not use compiler source offsets or retokenize the document. Provider/model provenance is descriptive; when contextual G2P requires a specific provider, the adapter must fail clearly or use its documented non-contextual fallback.

```python
for unit in plan.flow:
    for segment in unit.segments:
        tokens = [segment.text[token.start : token.end] for token in segment.tokens]
        phonemizer(segment.text, segment.language, tokens)
```

The renderer must not rerun spaCy or infer missing POS/tag values. No JSON serialization is required for in-process use.

## Pause behavior

The flow carries semantic pause intents and exact authored timed breaks, not planner-invented renderer durations or a renderer activation mode. PyKokoro may interpret supported semantic intents according to its own behavior. Renderer/acoustic variance remains outside UtterPlan and plan identity.

## Compatibility ownership

Consumer-specific compatibility and integration tests belong in the PyKokoro repository. UtterPlan's own test suite validates the public FlowPlan contract using repository-owned fixtures and goldens only.
