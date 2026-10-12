from __future__ import annotations

import importlib.resources
import importlib.util
from importlib.metadata import version

import utterplan
from utterplan import FlowPlan, PlannerConfig, UtterancePlanner


def test_public_package_identity() -> None:
    assert version("utterplan") == utterplan.__version__
    assert importlib.util.find_spec("ttsplan") is None


def test_public_planner_identity() -> None:
    plan = UtterancePlanner(PlannerConfig(language="en-us")).plan("Hello.")

    assert isinstance(plan, FlowPlan)
    payload = plan.to_dict()
    assert payload["format"] == "utterplan"
    assert payload["schema_version"] == 7
    assert payload["producer"]["name"] == "utterplan"
    assert payload["producer"]["text_preparation"] == "spokenform"


def test_public_package_resources() -> None:
    package = importlib.resources.files("utterplan")

    assert (package / "py.typed").is_file()
    assert (package / "compiler.py").is_file()
    assert (package / "utterplan.schema.json").is_file()
    schemas = package / "schemas"
    assert all((schemas / f"v{version}.schema.json").is_file() for version in (1, 2, 3, 4))
    assert (package / "codecs" / "v7_toml.py").is_file()
    assert not (schemas / "v7.schema.json").exists()
