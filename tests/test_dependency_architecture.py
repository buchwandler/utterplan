from __future__ import annotations

import ast
import re
from pathlib import Path

import tomlkit

ROOT = Path(__file__).resolve().parents[1]


def _requirement_name(requirement: str) -> str:
    match = re.match(r"([A-Za-z0-9_.-]+)", requirement)
    assert match is not None, f"invalid dependency declaration: {requirement!r}"
    return match.group(1).lower().replace("_", "-")


def test_runtime_dependencies_use_ttsready_without_direct_spokenform() -> None:
    project = tomlkit.parse((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    dependencies = project["dependencies"]
    by_name = {_requirement_name(item): item for item in dependencies}

    assert by_name["ttsready"] == "ttsready>=0.2.3,<0.3"
    assert "phrasplit" in by_name
    assert "ssmd" in by_name
    assert "spokenform" not in by_name

    optional = project.get("optional-dependencies", {})
    assert all(
        _requirement_name(item) != "spokenform" for group in optional.values() for item in group
    )


def test_production_sources_do_not_import_spokenform() -> None:
    for path in sorted((ROOT / "utterplan").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] != "spokenform" for alias in node.names), path
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] != "spokenform", path
