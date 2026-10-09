# Debugging

Start with the executable flow explanation before inspecting renderer or audio behavior:

```text
source / SSMD -> FlowPlan -> renderer diagnostics -> audio
                         \\-> optional compiler trace
```

`utterplan explain FILE` shows prepared segment text, flow order, languages, semantic pause intents, directives, markers, and headings. `utterplan inspect` shows local tokens and segment details. Compiler source diagnostics and preparation mappings are not embedded in FlowPlan; request and retain a trace sidecar when those details are needed after compilation:

```bash
utterplan compile chapter.ssmd.md -o chapter.utterplan.toml --trace chapter.trace.toml
utterplan explain chapter.utterplan.toml --trace chapter.trace.toml --details
utterplan inspect-trace chapter.trace.toml --preparation --boundaries
```

Safe punctuation-only repair is the default during compilation. If a semantic blocker prevents repair, the error includes source location, prepared fragment, spoken context, blocked repair reason, and a concrete next action; UtterPlan never guesses symbol pronunciation. Use `--renderability strict` to see safe repair opportunities without applying them. Batch compilation reports each repair and continues with later sources.

Use `inspect --tokens` to inspect local `TokenView` values. Fallback analysis may leave POS, tag, and morphology unavailable. `explain --details` shows token spans relative to the owning segment and its flow hash. Token spans always slice `segment.text`; they are not offsets into the original source or another segment.

If spoken wording is wrong, inspect `FlowSegment.text`. If effective language is wrong, inspect the segment and `FlowPlan.linguistics`. If a pause seems missing, distinguish the semantic `PauseIntent` on the segment edge from the consumer's engine-specific timing policy. Exact authored timed breaks remain explicit; semantic strengths do not prescribe a duration.

`utterplan inspect FILE --boundaries --tokens` operates only on persisted executable flow and does not require a renderer. Trace inspection shows compiler-only boundary events and candidates separately.

For source-coordinate bugs, inspect `PreparationTrace.source_text`, `source_spans`, and the structural/spoken maps. Source offsets address exact input Python characters, including SSMD headers and markup; diagnostic line and column are 1-based. Preparation transformation source ranges address structural text, while output ranges address prepared spoken text. See the [coordinate-space contract](coordinate-spaces).

If the FlowPlan is correct but G2P or audio is wrong, the issue belongs to the renderer or acoustic runtime, not the planning boundary.
