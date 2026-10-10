# Coordinate spaces

Schema v5 keeps the executable plan compact: token coordinates are local to each `FlowSegment.text`; document-global source and preparation coordinates live only in an optional `PreparationTrace` sidecar.

## Executable plan coordinates

`FlowSegment.text` is the prepared speech text for that segment. Each `TokenView.start` and `TokenView.end` is a half-open Python-character offset into that segment's text. Slice a token with `segment.text[token.start:token.end]`. Do not add a unit, segment, document, or compiler offset to these values. Token membership is stored locally in `segment.tokens`; there are no plan-global token indices or lookup joins.

Pauses, directives, markers, and optional heading levels are attached directly to their owning flow-segment edge or segment. They have no independent text coordinate. Flow-unit and segment order is the render order.

## Optional trace coordinates

Trace coordinates use Python string character boundaries (Unicode code points), not UTF-8 bytes or grapheme clusters:

- `source_text` is the exact caller input, including SSMD front matter and markup.
- `source_spans` maps original-source `[source_start, source_end)` ranges to parsed structural `[structural_start, structural_end)` ranges.
- `structural_text` is SSMD-clean structural text before written-to-spoken preparation.
- `spoken_text` is the prepared text used to construct executable segments.
- `structural_to_spoken` maps structural character boundaries to spoken boundaries; `spoken_to_structural` maps spoken boundaries back to structural boundaries.
- `PreparationTraceUnit.source_start` / `source_end` address structural text. `PreparationChange.source_start` / `source_end` use structural coordinates; `output_start` / `output_end` use prepared spoken coordinates.

## Compiler-only segmentation coordinates

Paragraph, sentence, and sentence-part spans use half-open Python-character offsets into the prepared global `spoken_text`. PhraseSplit offsets are run-local and are translated to global spoken coordinates exactly once before validation. Renderer segments retain the exact `spoken_text[start:end]` slice; language-run edges and other required renderer cuts do not change their owning paragraph, sentence, or part index. These spans are compiler topology, not fields in the v5 flow. Segmentation diagnostics map their spoken ranges back to exact source coordinates through the compiler's source map.

Diagnostic source offsets use the exact original-source coordinate space. Diagnostic `line` and `column` values are 1-based; columns count Python characters from the start of a line. The trace retains all these maps and source evidence. The executable FlowPlan intentionally does not.
