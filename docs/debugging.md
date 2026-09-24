# Debugging

Start with the integrated plan explanation before inspecting audio:

```text
source / SSMD -> document.utterplan.json -> renderer diagnostics -> audio
```

`utterplan explain FILE` shows prepared wording, render units, languages, resolved pauses, directives, markers, and warnings together. Use `utterplan inspect` when you need raw tokens, boundaries, coordinates, or a specific segment.

For SSMD plans, `explain` summarizes the parsed version, title and document language, heading events, effective typed directives, portable metadata, and warning/error codes with source locations. These are semantic plan diagnostics, not renderer execution results. UtterPlan parses SSMD 0.9 only. Migrate an older source file first with `ssmd migrate FILE --to 0.9`; `utterplan migrate` is for plan JSON schemas.

Use `inspect --tokens` to distinguish unavailable fallback fields (`pos=-`, `tag=-`, `morph=-`) from actual values. `explain --details` shows the final linguistic run provider/model and each segment's token snapshot.

If spoken wording is wrong, inspect `texts.spoken` and `preparation`. If language is wrong, inspect `languages` and annotation provenance. If a pause is missing, inspect `boundaries` and segment pause event IDs. If the plan is correct but G2P or audio is wrong, the issue belongs to the renderer or acoustic runtime, not the planning boundary.

`utterplan inspect FILE --boundaries --tokens` is intentionally human-readable and does not require a renderer.

For coordinate bugs, compare structural annotation ranges with their mapped spoken ranges and inspect preparation replacement provenance. SSMD annotations and diagnostics may also include half-open `source_start`/`source_end` offsets into the original input, including its header and markup. These are Unicode code point offsets for provenance, not render slicing; diagnostic line and column values are 1-based. The exact coordinate map is transient and unavailable after serialization. For pause bugs, distinguish `origin="ssmd"`, `origin="phrasplit"`, and `origin="planner"`, then inspect the contributing event IDs in `pause_before` or `pause_after`. Automatic clause and parenthetical pauses are mode-dependent; explicit SSMD breaks remain explicit, including zero-duration breaks.

If a closing parenthetical pause is missing, verify:

1. `detected_kind == "parenthetical_close"`.
2. `boundary.position == index(")") + 1` in spoken-text coordinates.
3. `attrs.anchor == "before"`.
4. The effective pause mode is `auto`.
5. The resumed segment's `pause_before` contains that boundary ID.

A detected automatic boundary and an active renderer-facing boundary are distinct. The detected event can remain in `plan.boundaries` for diagnostics even when the active pause policy leaves segmentation and resolved pauses unchanged.
