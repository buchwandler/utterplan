# UtterPlan

UtterPlan compiles text and SSMD into deterministic, engine-independent semantic
speech plans. It stops before G2P and synthesis.

```{toctree}
:maxdepth: 2
:caption: User guide

getting-started
cli
ssmdbook
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

The package version and the UtterPlan schema version are independent. The current interchange schema is version `6`; schema-v5 TOML and schemas v1–v4 remain available as immutable historical inputs with sequential migration paths.
