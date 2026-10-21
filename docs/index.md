# UtterPlan

UtterPlan compiles text and SSMD into deterministic, engine-independent semantic
speech plans. It stops before G2P and synthesis.

```{toctree}
:maxdepth: 2
:caption: User guide

getting-started
cli
Manifest-driven SSMD bundles <bundles>
consumer-guide
format
coordinate-spaces
debugging
```

```{toctree}
:maxdepth: 2
:caption: Developer guide

architecture
pykokoro-integration
python-api
changelog
```

The [bundle guide](bundles.md) documents canonical bundle roots, manifest dispatch, safe item paths, compilation, profile-specific RenderPlan projection, deterministic replanning, and the unified Python API.
The package version and the UtterPlan schema version are independent. Schema v7 is the only version accepted by normal loading and execution. Schema-v5/v6 TOML and schemas v1–v4 remain immutable historical migration inputs; the sequential path reaches v6, while v6-to-v7 requires recompiling the original source.
