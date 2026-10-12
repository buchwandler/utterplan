# Renderer consumer guide

UtterPlan ends at a semantic planning boundary. A renderer consumes the public `FlowPlan` and begins G2P after planning. It does not need a TOML round trip when planner and renderer run in the same process.

The schema-v7 plan is renderer-independent: `FlowUnit` grouping is fixed paragraph-local, while `FlowSegment` boundary arrays carry safe cut opportunities. Segments are not necessarily TTS calls, and UtterPlan's linguistic tokens are not model-token counts. A consumer may choose sentence, paragraph, or engine-token-budget chunks and native, automatic, or manual pause realization without changing the saved plan.

For persistence across processes, save a current plan as `.utterplan.toml` and load it with `FlowPlan.load()`. `to_toml()` / `from_toml()` provide text round-tripping, and `plan_id` identifies executable semantics rather than TOML formatting. Batch reports and optional compiler traces are operational/provenance artifacts, not plans.

UtterPlan accepts SSMD source syntax at version 0.9 only. Convert older source with `ssmd migrate FILE --to 0.9`; `utterplan migrate` is for importing serialized legacy plans.

## Importing legacy plans

Historical schemas retain their sequential data-only path through v6; v6-to-v7 migration refuses because it cannot reconstruct the complete boundary inventory, so recompile the original source. Import explicitly:

```bash
utterplan migrate old.utterplan.json --check
```

If the command reports `migration.recompile_required`, compile the original source to produce the complete schema-v7 boundary inventory.

Migration operates on serialized plain data and does not reparse, reprepare, rerun NLP, or replan. Earlier steps fail safely when token ownership/spans or authored pause semantics cannot be verified without guessing. V5-to-v6 never fabricates missing source text; v6-to-v7 returns `migration.recompile_required` rather than inventing boundaries. Recompile the original source as a separate operation. Normal `FlowPlan.load()` and plan-inspection commands reject JSON.

## Planning defaults

Text preparation defaults to `auto`: plain text resolves to TTSReady/Spokenform `spokenform`, while SSMD resolves to authoritative `ssmd` preparation that applies reviewed `sub` aliases without another Spokenform pass. Explicit `--text-preparation spokenform` on SSMD is a warned legacy mode; `ssmd` can also be selected explicitly, and `identity` preserves literal behavior. Applied `sub` aliases become segment text and are recorded as compact replacements, not executable substitution directives. Newly compiled v7 plans record the resolved preparation mode in informational `producer.text_preparation` metadata. There is no compile-time pause activation policy, and spaCy policy is best-effort `auto`; installed compatible local models are preferred in `sm`, `md`, `lg`, `trf` order, with deterministic fallback if unavailable. Provider documents remain internal. Use `--spacy off` to force fallback or a tier flag to require that model.

In Python, `PlannerConfig.document_format` defaults to `"plain"`; select `"ssmd"` for SSMD source. There is no `PauseConfig` or compile-time pause policy. The v7 plan stores authored pause directives separately from safe boundary opportunities; downstream renderers choose whether and how to realize them.

## Consumer contract

`FlowPlan.flow` is the render order. Each `FlowUnit` owns its ordered `FlowSegment` records; no ID join is required. A segment provides:

- `text`: prepared speech text for this segment.
- `language`: effective language, defaulting from `FlowPlan.language` when omitted on the wire.
- `tokens`: local token views with optional lemma, POS, tag, and morphology.
- `boundary_before` and `boundary_after`: safe canonical cut opportunities (`clause`, `sentence`, `paragraph`, `parenthetical`, `voice_change`), independent of pause realization.

- `pause_before` and `pause_after`: authored SSMD pause intents (`none`, strength, or exact timed break); automatic boundary opportunities are not pause intents.
- `directives`: typed voice, pronunciation, prosody, emphasis, say-as, substitution, audio, and extension data.
- `markers` and optional `heading` metadata already localized to the owning segment.

Token offsets are half-open Python-character ranges into the owning `segment.text`. Do not use them to slice document text or add offsets from another segment. Consumers preserve stored segment order but decide downstream chunk boundaries; a segment is not necessarily one TTS call.
Token `pos`, `tag`, `lemma`, and `morph` describe that exact prepared text and are the authoritative linguistic context, not model-token IDs or counts. Consumers may pass them through without retokenizing or rerunning spaCy. Optional replacements are provenance only: their output spans are segment-local, source values are original spellings, and they do not alter hashes independently of the source digest and are not synthesis inputs.

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

`FlowPlan.document` retains compact document information such as format, title, SSMD version, and portable semantics. `FlowPlan.linguistics` identifies analysis provider/model provenance without retaining provider state. Compact replacement views preserve local prepared-text spans and original spellings. The optional `FlowPlan.source` record (introduced in v6 and retained in v7) retains exact raw input once (and may be absent on migrated v5 plans). Source offsets, complete preparation mappings, compiler diagnostics, and renderability details still require an optional trace sidecar.

## Optional compiler trace

When source-level evidence must survive a process boundary, request a separate trace sidecar:

```bash
utterplan compile chapter.ssmd.md -o chapter.utterplan.toml --trace chapter.trace.toml
utterplan explain chapter.utterplan.toml --trace chapter.trace.toml
utterplan inspect-trace chapter.trace.toml --preparation --boundaries
```

The trace contains source text/hash, structural/prepared text, full coordinate maps, preparation changes, diagnostics, and renderability evidence. Exact raw input is stored in the optional v7 `FlowPlan.source` record; compact replacement views are available in v7 segments, while the trace remains necessary for original source offsets and complete mappings. The trace is not renderer input, does not affect `FlowPlan.plan_id`, and does not change the executable plan.

## Directives and media

Voice bindings and directive voice references are logical names, not backend voice IDs; consumers translate them to engine-specific resources. UtterPlan resolves SSMD scopes and defaults but does not choose engine settings or realize downstream pause policy; consumers interpret saved boundary and authored-pause facts.

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
