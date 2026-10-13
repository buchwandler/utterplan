from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from utterplan import PlannerConfig, PlanValidationError, compile_document
from utterplan.codecs.v5_toml import loads_v5_toml
from utterplan.exceptions import PlanFormatError, PlanMigrationError, UnsupportedSchemaError
from utterplan.flow_projection import _validate_replacement_ownership
from utterplan.hashing import V5_FLOW_HASH_SCHEMA
from utterplan.migration import migrate_plan_data
from utterplan.model import FlowPlan

ROOT = Path(__file__).resolve().parent
V5_FIXTURE = ROOT / "schema_history" / "v5" / "canonical_consumer_contract.toml"


def _compile(source: str) -> FlowPlan:
    return compile_document(
        source,
        input_format="ssmd",
        config=PlannerConfig(language="en-us", document_format="ssmd"),
    ).plan


def test_v7_plan_keeps_exact_source_once_and_roundtrips_its_digest() -> None:
    source = '[ART]{sub="A R T"}\n'
    plan = _compile(source)
    data = plan.to_dict()

    assert plan.schema_version == 7
    assert data["source"] == {
        "format": "ssmd",
        "text": source,
        "sha256": plan.source.sha256,
    }
    assert "source" not in data["document"]
    replacement = plan.flow[0].segments[0].replacements[0]
    assert replacement.source == "ART"
    assert replacement.surface(plan.flow[0].segments[0].text) == "A R T"
    assert plan.flow[0].segments[0].directives.substitution is None

    serialized = plan.to_toml()
    assert serialized.count("[source]") == 1
    restored = FlowPlan.from_toml(serialized)
    assert restored == plan
    assert restored.source is not None and restored.source.text == source
    assert restored.source.sha256 == plan.source.sha256


def test_source_digest_changes_plan_identity_but_not_renderer_unit_hashes() -> None:
    first = _compile('[ART]{sub="A R T"}')
    second = _compile('[ART]{sub="A R T"}\n')

    assert first.source.sha256 != second.source.sha256
    assert first.plan_id != second.plan_id
    assert [unit.content_hash for unit in first.flow] == [unit.content_hash for unit in second.flow]
    assert first.flow == second.flow


def test_frozen_v5_toml_is_explicit_migration_only(tmp_path: Path) -> None:
    raw = V5_FIXTURE.read_text(encoding="utf-8")
    frozen = loads_v5_toml(raw)
    before = frozen.to_dict()
    migrated = migrate_plan_data(before, target_version=6)

    assert frozen.schema_version == 5
    assert frozen.hash_schema == V5_FLOW_HASH_SCHEMA
    assert migrated.target_version == 6
    assert [(step.source_version, step.target_version) for step in migrated.steps] == [(5, 6)]
    assert migrated.data["schema_version"] == 6
    assert "source" not in migrated.data
    with pytest.raises(PlanMigrationError) as error:
        migrate_plan_data(before)
    assert error.value.code == "migration.recompile_required"
    with pytest.raises(UnsupportedSchemaError) as error:
        FlowPlan.from_toml(raw)
    legacy_path = tmp_path / "legacy.utterplan.toml"
    legacy_path.write_text(raw, encoding="utf-8")
    with pytest.raises(UnsupportedSchemaError):
        FlowPlan.load(legacy_path)
    assert error.value.code == "schema.version_unsupported"
    assert str(error.value).endswith(
        "This build accepts UtterPlan schema 7 only. Recompile the source with the current UtterPlan."
    )
    assert before == frozen.to_dict()
    assert V5_FIXTURE.read_text(encoding="utf-8") == raw


def test_v7_source_hash_is_verified_when_loading_semantic_data() -> None:
    data = _compile("Hello.").to_dict()
    data["source"]["sha256"] = "sha256:" + "0" * 64

    with pytest.raises(PlanFormatError, match="source.hash"):
        FlowPlan.from_dict(data)


def test_replacement_provenance_must_have_exactly_one_segment_owner() -> None:
    source = "A"
    spoken = "alias"
    replacement = {
        "source_start": 0,
        "source_end": 1,
        "output_start": 0,
        "output_end": 5,
        "source": source,
        "replacement": spoken,
        "kind": "ssmd-sub",
    }
    plan = SimpleNamespace(
        preparation=SimpleNamespace(replacements=(replacement,)),
        texts=SimpleNamespace(structural=source, spoken=spoken),
        segments=(
            SimpleNamespace(id="one", spoken_start=0, spoken_end=5),
            SimpleNamespace(id="two", spoken_start=0, spoken_end=5),
        ),
    )

    with pytest.raises(PlanValidationError, match="replacement.owner"):
        _validate_replacement_ownership(plan)
