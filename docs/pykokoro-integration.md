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

PyKokoro owns model selection, voice assets, G2P, model tokens, ONNX sessions, acoustic behavior, and audio. UtterPlan owns deterministic document parsing, language planning, written-to-spoken preparation, canonical segmentation, safe boundary opportunities, authored pause intents, typed directives, markers, and paragraph-local flow units.

## Thin adapter inputs

A future adapter can use only public v7 flow fields:

- `plan.flow` in order, with each unit's ordered `segments`;
- `segment.text` and `segment.language`;
- local `segment.tokens` for optional linguistic context;
- `segment.directives`, `pause_before`, and `pause_after`;
- `segment.boundary_before` / `boundary_after` for safe downstream cuts, separately from authored pause intents;
- `segment.markers` and optional `segment.heading`;
- compact `plan.document` and `plan.linguistics` metadata.

Token offsets are local to the owning `segment.text`. A consumer must not use compiler source offsets. Optional replacement spans slice prepared text and record original spellings; they are not source offsets. Preserve the trace sidecar for exact source locations and complete preparation mappings.

```python
for unit in plan.flow:
    for segment in unit.segments:
        tokens = [segment.text[token.start : token.end] for token in segment.tokens]
        phonemizer(segment.text, segment.language, tokens)
```

Use the v7 linguistic token fields (not model-token IDs or counts) as authoritative context: pass available `pos`, `tag`, `lemma`, and `morph` through unchanged rather than rerunning spaCy or inferring tags. Default `auto` uses installed compatible local models, preferring `sm`, `md`, `lg`, `trf`, and safely falls back if unavailable; model packages are never downloaded. When fields are unavailable, follow the adapter's documented non-contextual fallback.

## Pause behavior

Schema v7 carries safe boundary opportunities separately from authored pause intents and exact timed breaks; neither selects a renderer activation policy or fixes a chunk. PyKokoro may choose its own chunking and native, automatic, or manual pause realization. A `FlowSegment` is not necessarily one TTS call, and renderer/acoustic variance remains outside UtterPlan and plan identity.

## Compatibility ownership

Consumer-specific compatibility and integration tests belong in the PyKokoro repository. UtterPlan's own test suite validates the public FlowPlan contract using repository-owned fixtures and goldens only.
