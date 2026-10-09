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

The package version and the UtterPlan schema version are independent. The
current interchange schema is version `4`; schemas v1, v2, and v3 remain
available as immutable historical resources with sequential migration paths.
