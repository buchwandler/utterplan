from __future__ import annotations

import pytest

from utterplan import FlowPlan, FlowSegment, FlowUnit, PauseIntent, PlanSource
from utterplan.boundaries import BoundaryKind
from utterplan.codecs.v7_toml import to_v7_toml_data
from utterplan.exceptions import PlanFormatError, UnsupportedSchemaError
from utterplan.hashing import FLOW_HASH_SCHEMA
from utterplan.serialization import from_dict as load_flow_plan
from utterplan.toml_codec import from_toml_data


def _plan(
    *, boundary_after: tuple[BoundaryKind, ...] = (), pause_after: PauseIntent | None = None
) -> FlowPlan:
    segment = FlowSegment(
        "Hello.",
        "en-us",
        pause_after=pause_after,
        boundary_after=boundary_after,
    )
    return FlowPlan(
        language="en-us",
        flow=(FlowUnit((segment,)),),
        source=PlanSource("plain", "Hello."),
    )


@pytest.mark.parametrize("schema_version", [5, 6])
def test_normal_flow_plan_decoders_reject_legacy_schemas(schema_version: int) -> None:
    semantic = _plan().to_dict()
    semantic["schema_version"] = schema_version
    with pytest.raises(UnsupportedSchemaError) as error:
        FlowPlan.from_dict(semantic)
    assert error.value.code == "schema.version_unsupported"
    with pytest.raises(UnsupportedSchemaError):
        load_flow_plan(semantic)

    wire = to_v7_toml_data(_plan())
    wire["schema_version"] = schema_version
    with pytest.raises(UnsupportedSchemaError) as error:
        from_toml_data(wire)
    assert error.value.code == "schema.version_unsupported"


def test_v7_flow_has_no_root_unit_and_roundtrips_coexisting_boundary_and_authored_pause() -> None:
    plan = _plan(boundary_after=("sentence",), pause_after=PauseIntent("none"))

    data = plan.to_dict()
    toml = plan.to_toml()
    restored = FlowPlan.from_toml(toml)

    assert plan.schema_version == 7
    assert not hasattr(plan, "unit")
    assert plan.hash_schema == FLOW_HASH_SCHEMA == "utterplan-flow-v3"
    assert "unit" not in data
    assert "unit =" not in toml
    assert 'boundary_after = ["sentence"]' in toml
    assert 'pause_after = "none"' in toml
    assert restored == plan
    assert restored.flow[0].segments[0].boundary_after == ("sentence",)
    assert restored.flow[0].segments[0].pause_after == PauseIntent("none")


def test_v7_rejects_root_unit_and_automatic_pause_labels() -> None:
    data = _plan().to_dict()
    data["unit"] = "paragraph"
    with pytest.raises(PlanFormatError, match="unknown plan fields"):
        FlowPlan.from_dict(data)

    data = _plan().to_dict()
    data["flow"][0]["segments"][0]["pause_after"] = "sentence"
    data["flow"][0]["hash"] = FlowUnit(
        (FlowSegment("Hello.", "en-us", pause_after=PauseIntent("none")),)
    ).content_hash
    with pytest.raises(PlanFormatError):
        FlowPlan.from_dict(data)


def test_v7_boundary_wire_arrays_must_be_known_and_canonical() -> None:
    for boundary_values in (
        ["engine_token"],
        ["sentence", "sentence"],
        ["voice_change", "sentence"],
        ["clause", "sentence"],
    ):
        data = _plan().to_dict()
        data["flow"][0]["segments"][0]["boundary_after"] = boundary_values
        with pytest.raises(PlanFormatError):
            FlowPlan.from_dict(data)


def test_v7_boundary_opportunities_change_executable_identity() -> None:
    plain = _plan()
    bounded = _plan(boundary_after=("paragraph",))

    assert plain.flow[0].content_hash != bounded.flow[0].content_hash
    assert plain.plan_id != bounded.plan_id


def test_v7_codec_rejects_unknown_root_and_segment_fields() -> None:
    data = to_v7_toml_data(_plan())
    data["unit"] = "paragraph"
    with pytest.raises(PlanFormatError, match="unknown top-level TOML fields"):
        from_toml_data(data)

    data = to_v7_toml_data(_plan())
    data["flow"][0]["segment"][0]["renderer_tokens"] = 10
    with pytest.raises(PlanFormatError, match="unknown flow segment fields"):
        from_toml_data(data)


def test_v6_historical_reader_preserves_legacy_contract_without_promoting_to_v7() -> None:
    import tomlkit

    from utterplan import LegacyFlowPlan
    from utterplan.codecs.v6_toml import dumps_v6_toml, from_v6_toml_data, to_v6_toml_data
    from utterplan.exceptions import PlanMigrationError
    from utterplan.hashing import V6_FLOW_HASH_SCHEMA, flow_plan_id, flow_unit_hash
    from utterplan.migration import migrate_plan_data

    data = _plan(boundary_after=("sentence",), pause_after=PauseIntent("none")).to_dict()
    data["schema_version"] = 6
    data["hash_schema"] = V6_FLOW_HASH_SCHEMA
    data["unit"] = "paragraph"
    for unit in data["flow"]:
        for segment in unit["segments"]:
            segment.pop("boundary_before", None)
            segment.pop("boundary_after", None)
        unit["hash"] = flow_unit_hash(unit["segments"])
    data["plan_id"] = flow_plan_id(data)

    historical = LegacyFlowPlan.from_dict(data)
    wire = to_v6_toml_data(historical)
    restored = from_v6_toml_data(tomlkit.parse(dumps_v6_toml(historical)).unwrap())
    assert wire["unit"] == "paragraph"
    assert "boundary_after" not in wire["flow"][0]["segment"][0]

    assert isinstance(historical, LegacyFlowPlan)
    assert historical.unit == "paragraph"
    assert restored.to_dict() == historical.to_dict()
    assert "boundary_after" not in historical.to_dict()["flow"][0]["segments"][0]
    historical_data = historical.to_dict()
    with pytest.raises(PlanMigrationError) as error:
        migrate_plan_data(historical_data)
    assert error.value.code == "migration.recompile_required"
    assert historical_data == historical.to_dict()
