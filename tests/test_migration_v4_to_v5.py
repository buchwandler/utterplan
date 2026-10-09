from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from utterplan import UtterancePlanner
from utterplan.exceptions import PlanMigrationError
from utterplan.hashing import FLOW_HASH_SCHEMA, flow_plan_id, flow_unit_hash
from utterplan.migrations import migrate_v4_to_v5, migration_registry

FIXTURES = Path(__file__).parent / "migration" / "fixtures" / "v4"
MIGRATABLE = (
    "basic_en.utterplan.json",
    "directives.utterplan.json",
    "markers.utterplan.json",
    "multilingual.utterplan.json",
    "parenthetical.utterplan.json",
    "spokenform_offsets.utterplan.json",
    "ssmd_breaks.utterplan.json",
)


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _segments(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [segment for unit in plan["flow"] for segment in unit["segments"]]


def test_v4_fixtures_project_deterministically_without_mutating_input() -> None:
    for name in MIGRATABLE:
        source = _fixture(name)
        before = copy.deepcopy(source)

        first = migrate_v4_to_v5(source)
        second = migrate_v4_to_v5(source)

        assert source == before
        assert first == second
        assert first["schema_version"] == 5
        assert first["hash_schema"] == FLOW_HASH_SCHEMA
        assert first["plan_id"] == flow_plan_id(first)
        assert all(unit["hash"] == flow_unit_hash(unit["segments"]) for unit in first["flow"])
        assert not {
            "config",
            "preparation",
            "source",
            "texts",
            "tokens",
            "segments",
            "boundaries",
            "semantic_boundaries",
            "annotations",
            "markers",
            "units",
        }.intersection(first)


def test_token_facts_are_local_and_surface_verified() -> None:
    plan = migrate_v4_to_v5(_fixture("parenthetical.utterplan.json"))
    for segment in _segments(plan):
        for token in segment["tokens"]:
            assert segment["text"][token["start"] : token["end"]]
            assert token["start"] >= 0
            assert token["end"] <= len(segment["text"])

    split_token = _fixture("ssmd_09_comprehensive.utterplan.json")
    with pytest.raises(PlanMigrationError, match="cannot be verified") as error:
        migrate_v4_to_v5(split_token)
    assert error.value.code == "migration.token-coordinate-ambiguous"


def test_pause_migration_uses_provenance_not_numeric_thresholds() -> None:
    plan = migrate_v4_to_v5(_fixture("ssmd_breaks.utterplan.json"))
    segments = _segments(plan)

    assert segments[0]["pause_after"] == {"type": "timed", "time": "500ms"}
    assert segments[1]["pause_after"] == "none"
    assert all(
        segment.get("pause_before") != {"type": "timed", "time": "0ms"} for segment in segments
    )

    automatic = migrate_v4_to_v5(_fixture("markers.utterplan.json"))
    assert _segments(automatic)[0]["pause_after"] == "sentence"


def test_authored_numeric_pause_can_be_recovered_only_when_unambiguous() -> None:
    source = _fixture("ssmd_breaks.utterplan.json")
    event = source["boundaries"][0]
    event["attrs"].pop("time")
    event["seconds"] = None
    assert _segments(migrate_v4_to_v5(source))[0]["pause_after"] == {
        "type": "timed",
        "time": "500ms",
    }

    ambiguous = _fixture("ssmd_breaks.utterplan.json")
    explicit = ambiguous["boundaries"][0]
    explicit["attrs"].pop("time")
    explicit["seconds"] = None
    automatic = {
        "id": "boundary-auto",
        "kind": "sentence",
        "origin": "planner",
        "position": explicit["position"],
        "seconds": None,
        "strength": "sentence",
        "attrs": {"automatic": True},
    }
    ambiguous["boundaries"].append(automatic)
    ambiguous["segments"][0]["pause_after"]["events"].append("boundary-auto")
    with pytest.raises(
        PlanMigrationError, match="no recoverable strength or attributable duration"
    ) as error:
        migrate_v4_to_v5(ambiguous)
    assert error.value.code == "migration.pause-ambiguous"


def test_authored_pause_collisions_fail_instead_of_choosing_a_winner() -> None:
    source = _fixture("ssmd_breaks.utterplan.json")
    second = copy.deepcopy(source["boundaries"][0])
    second["id"] = "boundary-second-authored"
    source["boundaries"].append(second)
    source["segments"][0]["pause_after"]["events"].append(second["id"])

    with pytest.raises(PlanMigrationError, match="multiple authored pauses") as error:
        migrate_v4_to_v5(source)
    assert error.value.code == "migration.pause-ambiguous"


def test_directives_markers_and_headings_are_attached_to_segments() -> None:
    source = _fixture("markers.utterplan.json")
    source["boundaries"].append(
        {
            "id": "boundary-heading",
            "kind": "heading",
            "origin": "ssmd",
            "position": 5,
            "seconds": 0.0,
            "strength": None,
            "attrs": {"anchor": "before", "level": "2", "structural_only": True},
        }
    )
    source["segments"][1]["directives"]["audio"] = {"src": "sfx:door.open"}

    plan = migrate_v4_to_v5(source)
    segments = _segments(plan)
    assert segments[1]["markers"] == ["mark"]
    assert segments[1]["heading"] == 2
    assert segments[1]["directives"]["audio"] == {"src": "sfx:door.open"}

    directive_plan = migrate_v4_to_v5(_fixture("directives.utterplan.json"))
    assert _segments(directive_plan)[0]["directives"]["emphasis"] == {"level": "strong"}


def test_migration_does_not_invoke_planner_and_is_registered_sequentially(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("migration must not invoke fresh compilation")

    monkeypatch.setattr(UtterancePlanner, "plan", fail_if_called)
    migrated = migrate_v4_to_v5(_fixture("basic_en.utterplan.json"))

    assert migrated["schema_version"] == 5
    assert migration_registry()[4] is migrate_v4_to_v5


def test_plan_identity_ignores_producer_and_warning_metadata() -> None:
    plan = migrate_v4_to_v5(_fixture("basic_en.utterplan.json"))
    with_metadata = copy.deepcopy(plan)
    with_metadata["producer"] = {"name": "other", "version": "99"}
    with_metadata["warnings"] = ["debug-only"]
    assert flow_plan_id(with_metadata) == flow_plan_id(plan)
