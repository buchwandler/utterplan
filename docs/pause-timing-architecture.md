# Context-aware pause timing architecture

UtterPlan chooses semantic pause opportunities when compiling a source document, but final milliseconds are selected during optional RenderPlan projection. This keeps compilation profile-independent and lets existing schema-v7 FlowPlans benefit without migration.

```text
FlowPlan v7
  semantic boundary + local text/token/heading facts
        |
        v
RenderProfile
  baseline pause duration
        |
        v
UtterPlan RenderPlan projection
  fixed | natural | engaging timing policy
        |
        v
RenderPlan
  concrete PauseItem.duration_ms
        |
        v
VoiceRender -> AudioCompose
  speech synthesis -> materialize the selected silence
```

The RenderProfile remains the macro pacing control. `fixed` is the compatibility default and uses its configured automatic pause durations unchanged. `natural` and `engaging` apply deterministic, context-sensitive adjustments only to already-materialized automatic clause, sentence, and paragraph pauses. The policy uses only facts already present in the FlowPlan; it neither creates boundary positions nor loads NLP providers during projection.

Authored timing is more authoritative than adaptation: explicit millisecond pauses, named strengths, and authored `none` keep their existing resolution. Capacity-cut pauses remain unchanged, and voice-change pauses stay fixed. Replanning preserves existing PauseItems and does not rerun the timing policy, so an explicit timing mode is accepted only for initial projection.

The policy is a projection concern, not compilation semantics: it adds no fields to `.utterplan.toml`, changes neither the RenderProfile nor RenderPlan contract, and does not alter speech segmentation or topology. The chosen preset is reported as UtterPlan provenance and is incorporated into adaptive bundle variant labels to avoid output collisions. See the [CLI guide](cli.md#produce-or-replan-a-renderplan), [Python API](python-api.md#build-and-replan-a-renderplan), and [bundle guide](bundles.md#render) for usage.

## Listening evaluation

Compare fixed, natural, and engaging variants rendered from the same synthesized speech WAVs. Listen for repeated sentence cadence, short consecutive sentences, long explanatory sentences, questions, exclamations, ellipses, paragraph and dialogue transitions, authored pauses, and total inserted silence. The primary question is whether sentence boundaries stop sounding like a timer; also check whether engaging feels rushed. Do not judge only by chapter duration. If it sounds rushed, tune the engaging preset's bias or clamps rather than moving timing out of the projection layer.
