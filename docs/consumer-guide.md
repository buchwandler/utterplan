# Renderer consumer guide

UtterPlan ends at a semantic planning boundary. A renderer consumes the public `FlowPlan` and begins G2P after planning. It does not need a TOML round trip when planner and renderer run in the same process.

For persistence across processes, save a current plan as `.utterplan.toml` and load it with `FlowPlan.load()`. `to_toml()` / `from_toml()` provide text round-tripping, and `plan_id` identifies executable semantics rather than TOML formatting. Batch reports and optional compiler traces are operational/provenance artifacts, not plans.

UtterPlan accepts SSMD source syntax at version 0.9 only. Convert older source with `ssmd migrate FILE --to 0.9`; `utterplan migrate` is for importing serialized legacy plans.

## Importing legacy plans

Historical JSON schemas v1–v4 remain immutable and supported through sequential migrations to schema v5. Import explicitly:

```bash
utterplan migrate old.utterplan.json -o current.utterplan.toml
```

Migration operates on serialized plain data and does not reparse, reprepare, rerun NLP, or replan. The v4-to-v5 projection fails safely if token ownership/spans or authored pause semantics cannot be verified without guessing. Recompiling source is a separate operation. Normal `FlowPlan.load()` and plan-inspection commands reject JSON.

## Planning defaults

The default text-preparation backend is `spokenform`, pause activation mode is `tts`, and the default CLI linguistic-resource policy is `spacy off`. Deterministic fallback tokenization and analysis do not require an installed spaCy model. `spacy auto` is opt-in; it may expose richer tokenization, POS, lemmas, and tags, but provider documents remain internal.

In Python, `PlannerConfig.document_format` defaults to `"plain"`; select `"ssmd"` for SSMD source. `PauseConfig.mode` controls whether eligible semantic pause intents are activated by the compiler. The executable plan carries semantic intent (or an exact authored timed pause), not numeric durations invented from an activation policy. A renderer may interpret supported intents according to its own capabilities.

## Consumer contract

`FlowPlan.flow` is the render order. Each `FlowUnit` owns its ordered `FlowSegment` records; no ID join is required. A segment provides:

- `text`: prepared speech text for this segment.
- `language`: effective language, defaulting from `FlowPlan.language` when omitted on the wire.
- `tokens`: local token views with optional lemma, POS, tag, and morphology.
- `pause_before` and `pause_after`: semantic pause intents such as `none`, `sentence`, `parenthetical`, or an exact authored time.
- `directives`: typed voice, pronunciation, prosody, emphasis, say-as, substitution, audio, and extension data.
- `markers` and optional `heading` metadata already localized to the owning segment.

Token offsets are half-open Python-character ranges into the owning `segment.text`. Do not use them to slice document text or add offsets from another segment. Consumers render flow units and segments in their stored order.

```python
from utterplan import FlowPlan

plan = FlowPlan.load("chapter.utterplan.toml")
plan.validate()

for unit in plan.flow:
    for segment in unit.segments:
        token_views = [
            (segment.text[token.start : token.end], token.lemma, token.pos, token.tag, token.morph)
            for token in segment.tokens
        ]
        render_speech(
            text=segment.text,
            language=segment.language,
            tokens=token_views,
            pause_before=segment.pause_before,
            pause_after=segment.pause_after,
            directives=segment.directives,
        )
```

`FlowPlan.document` retains compact document information such as format, title, SSMD version, and portable semantics. `FlowPlan.linguistics` identifies analysis provider/model provenance without retaining provider state. Source text, source locations, compiler diagnostics, preparation mappings, and renderability details are intentionally not executable-plan fields.

## Optional compiler trace

When source-level evidence must survive a process boundary, request a separate trace sidecar:

```bash
utterplan compile chapter.ssmd.md -o chapter.utterplan.toml --trace chapter.trace.toml
utterplan explain chapter.utterplan.toml --trace chapter.trace.toml
utterplan inspect-trace chapter.trace.toml --preparation --boundaries
```

The trace contains source text/hash, structural/prepared text, coordinate maps, preparation changes, diagnostics, and renderability evidence. It is not renderer input, does not affect `FlowPlan.plan_id`, and does not change the resulting plan TOML. See the [coordinate-space contract](coordinate-spaces) for every trace offset's coordinate space.

## Directives and media

Voice bindings and directive voice references are logical names, not backend voice IDs; consumers translate them to engine-specific resources. UtterPlan resolves SSMD scopes and defaults but does not choose engine settings or recompute pause policy.

An audio directive is already attached to its owning segment. Its `src` is opaque data for an external resolver; UtterPlan does not select or invoke one. For an audio-bearing segment, `segment.text` is an optional spoken fallback. Identical source URIs on distinct segments are separate timeline occurrences and must not be deduplicated as playback events. Extension references are also data only; UtterPlan does not execute handlers.

## Stable renderer input

A completed plan is immutable consumer input. Consumers may derive data for G2P/rendering, but must not rewrite planning decisions or mutate the plan:

```python
before = plan.to_toml()
plan_id = plan.plan_id
consume_plan(plan)
assert plan.to_toml() == before
assert plan.plan_id == plan_id
```

Plans contain no phonemes, model token IDs, model sessions, audio, renderer configuration, or model-derived timings. Acoustic retries and renderer-level randomness remain outside UtterPlan.
