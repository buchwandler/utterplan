from __future__ import annotations

from pathlib import Path

import tomlkit
from renderplan import (
    RENDERPLAN_SET_FORMAT,
    RENDERPLAN_SET_VERSION,
    RenderPlan,
    RenderPlanSet,
    RenderPlanSetChapter,
    RenderProfile,
    load_renderplan_set,
    save_renderplan_set,
)

_PUBLIC_TYPES = (RenderPlan, RenderPlanSet, RenderPlanSetChapter, RenderProfile)
_PUBLIC_CODECS = (load_renderplan_set, save_renderplan_set)


def test_renderplan_minimum_public_api_is_available() -> None:
    assert RENDERPLAN_SET_FORMAT == "renderplan-set"
    assert RENDERPLAN_SET_VERSION == 1
    assert all(isinstance(value, type) for value in _PUBLIC_TYPES)
    assert all(callable(value) for value in _PUBLIC_CODECS)


def test_renderplan_collection_api_minimum_is_declared_as_runtime_dependency() -> None:
    project = tomlkit.parse(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    ).unwrap()
    assert "renderplan>=0.2.1,<0.3" in project["project"]["dependencies"]
