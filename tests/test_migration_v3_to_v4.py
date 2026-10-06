from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import jsonschema

from utterplan import UtterancePlan, migrate_plan_data
from utterplan.format import schema
from utterplan.hashing import UNIT_HASH_SCHEMA, semantic_hash, unit_hash_payload_from_serialized
from utterplan.migrations import migrate_v3_to_v4

FIXTURES = Path(__file__).parent / "schema_history" / "v3"


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_v3_to_v4_normalizes_clause_after_punctuation_and_preserves_event() -> None:
    original = _fixture("ssmd_09_comprehensive.json")
    spoken = original["texts"]["spoken"]
    comma = spoken.index(",")
    event = {
        "id": "boundary-legacy-clause",
        "position": comma,
        "kind": "clausal_comma",
        "seconds": None,
        "origin": "phrasplit",
        "strength": "weak",
        "attrs": {"automatic": True},
    }
    original["boundaries"].append(event)
    before = copy.deepcopy(original)

    result = migrate_plan_data(original)
    migrated = result.data
    assert list(migrated).index("semantic_boundaries") + 1 == list(migrated).index("boundaries")
    clause = next(item for item in migrated["semantic_boundaries"] if item["kind"] == "clause")

    assert result.source_version == 3
    assert result.target_version == 4
    assert result.steps[0].source_version == 3
    assert result.steps[0].target_version == 4
    assert clause["position"] == comma + 2  # comma and following horizontal space stay left
    assert clause["origin"] == "phrasplit"
    assert clause["attrs"]["migrated_from_boundary_id"] == event["id"]
    assert clause["attrs"]["migrated_from_position"] == comma
    assert migrated["boundaries"] == original["boundaries"]
    assert original == before
    jsonschema.validate(migrated, schema(4))
    assert UtterancePlan.from_dict(original).semantic_boundaries


def test_v3_to_v4_converts_legacy_semantic_events_only() -> None:
    original = _fixture("ssmd_09_comprehensive.json")
    existing_positions = {event["position"] for event in original["boundaries"]}
    positions = iter(
        position
        for position in range(1, len(original["texts"]["spoken"]) - 1)
        if position not in existing_positions
    )
    source_kinds = {
        "legacy-clause": ("clausal_comma", "clause"),
        "legacy-parenthetical": ("parenthetical", "parenthetical"),
        "legacy-sentence": ("sentence", "sentence"),
        "legacy-paragraph": ("paragraph", "paragraph"),
    }
    for boundary_id, (event_kind, _semantic_kind) in source_kinds.items():
        original["boundaries"].append(
            {
                "id": boundary_id,
                "position": next(positions),
                "kind": event_kind,
                "seconds": None,
                "origin": "legacy-test",
                "strength": None,
                "attrs": {},
            }
        )
    ignored_events = (
        ("legacy-explicit", "explicit"),
        ("legacy-heading", "heading"),
        ("legacy-voice", "voice_change"),
    )
    ignored_ids = {boundary_id for boundary_id, _event_kind in ignored_events}
    for boundary_id, event_kind in ignored_events:
        original["boundaries"].append(
            {
                "id": boundary_id,
                "position": next(positions),
                "kind": event_kind,
                "seconds": None,
                "origin": "legacy-test",
                "strength": None,
                "attrs": {},
            }
        )

    migrated = migrate_plan_data(original).data
    by_source_id = {
        boundary.get("attrs", {}).get("migrated_from_boundary_id"): boundary["kind"]
        for boundary in migrated["semantic_boundaries"]
    }

    for boundary_id, (_event_kind, semantic_kind) in source_kinds.items():
        assert by_source_id[boundary_id] == semantic_kind
    assert not ignored_ids.intersection(by_source_id)
    assert migrated["boundaries"] == original["boundaries"]


def test_v3_to_v4_does_not_invent_missing_clause_analysis() -> None:
    original = _fixture("multilingual.json")
    result = migrate_plan_data(original)

    assert not any(boundary["kind"] == "clause" for boundary in result.data["semantic_boundaries"])
    assert result.data["schema_version"] == 4


def test_v3_to_v4_derives_missing_sentence_and_paragraph_topology() -> None:
    original = _fixture("ssmd_09_comprehensive.json")
    original["boundaries"] = [
        event for event in original["boundaries"] if event["kind"] not in {"sentence", "paragraph"}
    ]
    expected: set[tuple[int, str]] = set()
    for previous, current in zip(original["segments"], original["segments"][1:], strict=False):
        if previous["paragraph"] != current["paragraph"]:
            expected.add((previous["spoken_end"], "paragraph"))
        elif previous["sentence"] != current["sentence"]:
            expected.add((previous["spoken_end"], "sentence"))

    result = migrate_plan_data(original)
    actual = {
        (boundary["position"], boundary["kind"]) for boundary in result.data["semantic_boundaries"]
    }

    assert expected <= actual


def test_v3_to_v4_is_deterministic_rehashes_units_and_records_provenance() -> None:
    original = _fixture("ssmd_09_comprehensive.json")
    first = migrate_plan_data(original)
    second = migrate_plan_data(original)
    result = first.data

    assert result == second.data
    assert result["plan_id"] != original["plan_id"]
    assert result["producer"]["migration"] == {
        "original_schema_version": 3,
        "original_plan_id": original["plan_id"],
        "steps": [{"from": 3, "to": 4}],
    }
    for unit in result["units"]:
        assert unit["content_hash_schema"] == UNIT_HASH_SCHEMA
        assert unit["content_hash"] == semantic_hash(
            unit_hash_payload_from_serialized(unit, result)
        )
    assert migrate_v3_to_v4(original)["schema_version"] == 4
