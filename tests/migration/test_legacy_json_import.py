from __future__ import annotations

import json
from pathlib import Path

import pytest

from utterplan import UtterancePlan
from utterplan.cli import main

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "v4"


def test_frozen_v4_json_fixtures_import_only_to_toml(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sources = sorted(FIXTURES.glob("*.utterplan.json"))
    assert len(sources) == 8

    for source in sources:
        original_text = source.read_text(encoding="utf-8")
        expected = UtterancePlan.from_dict(json.loads(original_text))
        destination = tmp_path / f"{source.stem}.toml"

        assert main(["migrate", str(source), "-o", str(destination)]) == 0
        assert "imported" in capsys.readouterr().err
        assert destination.suffix == ".toml"
        assert UtterancePlan.load(destination) == expected
        assert source.read_text(encoding="utf-8") == original_text
