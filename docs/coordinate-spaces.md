# Coordinate spaces

UtterPlan uses explicit coordinate names. `spoken_start`, `spoken_end`, and `spoken_position` refer to half-open offsets into `texts.spoken`. Token, annotation-spoken, language-run, marker, unit, and segment ranges consumed by a renderer use this prepared/synthesis-space coordinate system.

`structural_start` and `structural_end` refer to half-open offsets into `texts.structural`. The source field contains exact caller input, which may include SSMD headers and markup; source offsets are not fabricated for renderer slicing.

SSMD `source_start` and `source_end` are half-open Python string offsets (Unicode code points) into the exact original source, including any header and markup. They are source provenance only, not offsets into `texts.structural` or `texts.spoken`. Diagnostic `line` and `column` values are 1-based; columns count Python Unicode code points from the beginning of the source line.

When written-to-spoken preparation changes text, the planner uses an exact transient source-to-spoken map to resolve annotations, boundaries, and markers. The serialized plan stores only preparation provenance and resolved coordinates. Renderers must use `AnnotationSpan.spoken_start` and `spoken_end` when mapping annotations into `PlanSegment.text`; structural offsets must not be used to slice prepared text.

Linguistic token fields (`spoken_start`, `spoken_end`, `text`, `language`, `lemma`, `pos`, `tag`, and `morph`) are self-contained and refer to prepared text. `text` must equal the corresponding slice of `texts.spoken`. `segment.token_indices` is the stable membership relation, and `UtterancePlan.tokens_for_segment()` exposes it without retokenization. Provider documents are not part of the public plan.
