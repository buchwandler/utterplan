from __future__ import annotations

import json
from pathlib import Path

import pytest

from utterplan import FlowPlan, UtterancePlan
from utterplan.cli import main

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "v4"


def test_frozen_v4_json_fixtures_import_only_to_toml(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sources = sorted(FIXTURES.glob("*.utterplan.json"))
    assert len(sources) == 8

    for source in sources:
        original_text = source.read_text(encoding="utf-8")
        legacy = json.loads(original_text)
        UtterancePlan.from_dict(legacy)
        destination = tmp_path / f"{source.stem}.toml"

        if source.name == "ssmd_09_comprehensive.utterplan.json":
            assert main(["migrate", str(source), "-o", str(destination)]) == 1
            assert "migration.token-coordinate-ambiguous" in capsys.readouterr().err
            assert not destination.exists()
        else:
            assert main(["migrate", str(source), "-o", str(destination)]) == 0
            assert "imported" in capsys.readouterr().err
            assert destination.suffix == ".toml"
            migrated = FlowPlan.load(destination)
            assert migrated.schema_version == 5
            assert FlowPlan.from_toml(destination.read_text(encoding="utf-8")) == migrated

        assert source.read_text(encoding="utf-8") == original_text
