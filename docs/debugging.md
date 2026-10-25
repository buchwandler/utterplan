# Debugging

Start with the executable flow explanation before inspecting renderer or audio behavior:

```text
source / SSMD -> FlowPlan -> renderer diagnostics -> audio
                         \\-> optional compiler trace
```

`utterplan explain FILE` shows prepared segment text, paragraph-local flow order, languages, safe boundary opportunities, authored pause intents, directives, markers, headings, compact replacement views, and tokens. `utterplan inspect` shows local tokens and segment details. Complete source diagnostics and preparation mappings are not embedded in FlowPlan; request and retain a trace sidecar when those details are needed after compilation:

```bash
utterplan compile chapter.ssmd.md -o chapter.utterplan.toml --trace chapter.trace.toml
utterplan explain chapter.utterplan.toml --trace chapter.trace.toml --details
utterplan inspect-trace chapter.trace.toml --preparation --boundaries
```

To inspect what a saved plan exposes under downstream chunk and pause choices, use the pure preview command:

```bash
utterplan preview chapter.utterplan.toml \
  --segments 58-62 \
  --chunk-by clause \
  --pause-policy automatic \
  --details
```

The selector uses global zero-based flow-segment indexes and focuses complete containing chunks. Preview concatenates stored segment text exactly (including boundary spaces) and displays stored local token/replacement spans without rewriting them. Use `--json` for a versioned machine-readable result. If a spoken-space or substitution-provenance issue appears, inspect `FlowSegment.text` and its local replacement span rather than trimming preview output.

Safe punctuation-only repair is the default during compilation. If a semantic blocker prevents repair, the error includes source location, prepared fragment, spoken context, blocked repair reason, and a concrete next action; UtterPlan never guesses symbol pronunciation. Use `--renderability strict` to see safe repair opportunities without applying them. Batch diagnostics default to warnings: informational token reanalysis is suppressed rather than called a repair. Use `--diagnostics all` to display informational records or `--diagnostics none` to suppress non-failure detail; failures are always reported and complete diagnostics remain in the operational report.

Sentence segmentation is a compiler-integrity step, not a renderability repair. PhraseSplit is advisory: dependency failure or a malformed/partial proposal batch produces a `segmentation.phrasplit_*` diagnostic and triggers conservative fallback. Safe commas between lexical content can add soft `clause` opportunities during compilation; candidates respect atomic replacement/media spans and token-edge reconciliation. Unsafe candidates are dropped or merged before projection; exact text and non-whitespace coverage are checked in both strict and repair modes. Inspect compiler diagnostics with `compile --trace FILE` and `inspect-trace FILE --boundaries`; sentence-part spans remain private in v7; safe canonical boundary kinds are persisted separately from authored pauses.

Use `inspect --tokens` to inspect local `TokenView` values. V7 `pos`, `tag`, `lemma`, and `morph` describe prepared segment text and are authoritative linguistic context, not model-token IDs or counts; fallback analysis may leave some unavailable. `explain --details` shows token and compact replacement spans relative to the owning segment and its flow hash. These output spans are not offsets into original source or another segment; use the trace for complete source mappings.

If spoken wording is wrong, inspect `FlowSegment.text`. If effective language is wrong, inspect the segment and `FlowPlan.linguistics`. If a pause seems missing, distinguish an authored `PauseIntent` from a safe sentence/paragraph boundary opportunity; the consumer chooses native, automatic, or manual realization. Exact authored timed breaks remain explicit, while automatic boundary kinds carry no duration or pause command.

`utterplan inspect FILE --boundaries --tokens` operates only on persisted executable flow and does not require a renderer. Trace inspection shows compiler-only boundary events and candidates separately.

For source-coordinate bugs, inspect `PreparationTrace.source_text`, `source_spans`, and the structural/spoken maps. Source offsets address exact input Python characters, including SSMD headers and markup; diagnostic line and column are 1-based. Preparation transformation source ranges address structural text, while output ranges address prepared spoken text. See the [coordinate-space contract](coordinate-spaces).

If the FlowPlan is correct but G2P or audio is wrong, the issue belongs to the renderer or acoustic runtime, not the planning boundary.

## RenderProfile identity mismatch

A RenderProfile's `profile_id` identifies its canonical semantic content, not its TOML serialization. The error `profile_id does not match profile content` means the persisted ID is stale for the current profile semantics. UtterPlan fails closed and names the profile path; it does not repair or re-hash the profile, and `--force` does not bypass validation.

Regenerate or re-save the complete engine-backed RenderProfile with VoiceRender, then validate it before invoking UtterPlan:

```bash
voicerender profile validate narration.renderprofile.toml
utterplan bundle render story.ssmd-bundle --profile narration.renderprofile.toml --force
```

Do not use `sha256sum` on the TOML file as a replacement ID. If VoiceRender created the file and it was not manually edited, report the producer path for investigation; all binding and renderer metadata must be assembled before the final profile identity is persisted.
