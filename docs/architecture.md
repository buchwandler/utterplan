# Architecture

```text
text / SSMD -> document parser -> language plan -> linguistic pass A
    -> written-to-spoken preparation -> linguistic pass B
    -> segmentation -> directive resolution -> pause planning
    -> units and hashes -> UtterancePlan -> external renderer
                                      -> engine-specific G2P and speech
```

UtterPlan is the complete source-to-semantic-plan compiler boundary. G2P begins after the UtterPlan boundary. The public `UtterancePlan` Python object is a supported immutable in-process renderer input; the `.utterplan.json` schema is the portable persistence and semantic interchange contract.

Preparation preserves structural and spoken coordinate spaces. `spoken_start`, `spoken_end`, and `spoken_position` refer to prepared text. Renderers must use these ranges when consuming `PlanSegment.text`, `AnnotationSpan`, and `TokenAnnotation`; structural/source offsets are not valid slices into prepared text.

Linguistic analysis and provider documents are request-local. Returned plans contain JSON-compatible semantic results only: no live parser objects, spaCy documents, models, sessions, provider caches, phonemes, engine token IDs, or audio. A reusable planner may share sequential resource caches, but concurrent use is not promised.

The persisted `linguistic_runs` collection describes final pass-B token ranges. Pass-A documents and tokens remain request-local because written-to-spoken preparation can invalidate their offsets.

Pause events retain provenance and resolved event IDs. Pause defaults are normalized to finite seconds with explicit precedence, and segments expose resolved base pauses directly. Logical voices are intent references; document `voice_bindings` metadata remains separate and no concrete engine voice is selected.

Plan identity is deterministic and renderer-independent. Unit hashes include ordered segment semantics, resolved pauses, marker content, and the semantic token facts referenced by each segment. Diagnostics and producer metadata do not define unit identity. Package version is derived by setuptools-scm and is independent of the explicit UtterPlan `schema_version`.

## Persistence compatibility boundary

```text
                         .utterplan.json
                                |
                                v
                       inspect schema version
                                |
                    +-----------+-----------+
                    |                       |
                 current                    old
                    |                       |
                    |                 migration chain
                    |                       |
                    +-----------+-----------+
                                |
                                v
                      current UtterancePlan
                                |
                                v
                            renderer
```

Migration is not planning. UtterPlan owns persistence, schema validation, and migration. Renderers consume only the current in-memory `UtterancePlan` and do not implement historical schema branches.
