import json
from pathlib import Path

import pytest

from tests.compiler_helpers import CompilerTestPlanner as UtterancePlanner
from utterplan import PlanFormatError, PlannerConfig, UtterancePlan
from utterplan.format import schema


def test_unversioned_schema_paths_remain_v4_compatibility_aliases_only():
    source = json.loads(Path("spec/utterplan.schema.json").read_text())
    packaged = json.loads(Path("utterplan/utterplan.schema.json").read_text())
    assert packaged == source
    assert source["properties"]["schema_version"]["const"] == 4
    assert schema() == source


def test_nested_text_types_are_not_coerced():
    value = UtterancePlanner(PlannerConfig(language="en-us")).plan("Hello.").to_dict()
    value["texts"]["spoken"] = 123
    with pytest.raises(PlanFormatError, match="field.type"):
        UtterancePlan.from_dict(value)


def test_unknown_preparation_key_is_rejected():
    value = UtterancePlanner(PlannerConfig(language="en-us")).plan("Hello.").to_dict()
    value["preparation"]["unexpected"] = True
    with pytest.raises(PlanFormatError, match="preparation"):
        UtterancePlan.from_dict(value)
