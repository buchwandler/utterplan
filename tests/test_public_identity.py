from __future__ import annotations

import importlib.resources
import importlib.util
from importlib.metadata import version

import utterplan
from utterplan import PlannerConfig, UtterancePlan, UtterancePlanner


def test_public_package_identity() -> None:
    assert version("utterplan") == utterplan.__version__
    assert importlib.util.find_spec("ttsplan") is None


def test_public_planner_identity() -> None:
    plan = UtterancePlanner(PlannerConfig(language="en-us")).plan("Hello.")

    assert isinstance(plan, UtterancePlan)
    payload = plan.to_dict()
    assert payload["format"] == "utterplan"
    assert payload["schema_version"] == 3
    assert payload["producer"]["name"] == "utterplan"


def test_public_package_resources() -> None:
    package = importlib.resources.files("utterplan")

    assert (package / "py.typed").is_file()
    assert (package / "utterplan.schema.json").is_file()
    schemas = package / "schemas"
    assert all((schemas / f"v{version}.schema.json").is_file() for version in (1, 2, 3))
