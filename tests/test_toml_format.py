from __future__ import annotations

import copy
import datetime
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import tomlkit

from utterplan import (
    DocumentInfo,
    EmphasisDirective,
    FlowPlan,
    FlowSegment,
    FlowUnit,
    LinguisticProvenance,
    PauseIntent,
    PlanValidationError,
    SegmentDirectives,
    TokenView,
)
from utterplan.codecs.v4_toml import decode_v4_toml_data
from utterplan.exceptions import PlanFormatError, PlanMigrationError, UnsupportedSchemaError
from utterplan.hashing import FLOW_HASH_SCHEMA
from utterplan.migrations import migrate_v4_to_v5
from utterplan.toml_codec import dumps_toml, from_toml_data, loads_toml, to_toml_data

ROOT = Path(__file__).resolve().parent
V4_TOML = ROOT / "golden" / "basic_en.utterplan.toml"
V4_AMBIGUOUS_TOML = ROOT / "golden" / "ssmd_09_comprehensive.utterplan.toml"
V4_JSON = ROOT / "migration" / "fixtures" / "v4" / "basic_en.utterplan.json"


def _plan() -> FlowPlan:
    segment = FlowSegment(
        text="My life changed.",
        language="en-US",
        pause_after=PauseIntent("timed", "500ms"),
        directives=SegmentDirectives(emphasis=EmphasisDirective("strong")),
        tokens=(
            TokenView(
                0,
                2,
                lemma="my",
                pos="PRON",
                tag="PRP$",
                morph="Number=Sing|Person=1|Poss=Yes|PronType=Prs",
            ),
            TokenView(3, 7, lemma="life", pos="NOUN", tag="NN"),
            TokenView(8, 15, lemma="change", pos="VERB", tag="VBD", morph="Tense=Past"),
        ),
        markers=("chapter-one",),
        heading=2,
    )
    translated = FlowSegment(
        text="Outer voice.",
        language="fr-FR",
        boundary_before=("voice_change",),
        tokens=(TokenView(0, 5, pos="ADJ", tag="JJ"), TokenView(6, 11, pos="NOUN", tag="NN")),
    )
    return FlowPlan(
        language="en-US",
        flow=(FlowUnit((segment, translated)),),
        document=DocumentInfo(
            format="ssmd",
            ssmd_version="0.9",
            title="Chapter one",
            semantics={"voice_bindings": {"narrator": "en-US"}},
        ),
        linguistics=(
            LinguisticProvenance(language="en-US", provider="spacy", model="en_core_web_lg"),
            LinguisticProvenance(language="fr-FR", provider="fallback"),
        ),
        producer={"name": "utterplan", "version": "0.5.0"},
    )


def test_current_v7_toml_roundtrip_is_deterministic_and_semantically_identical() -> None:
    plan = _plan()
    text = dumps_toml(plan)
    restored = loads_toml(text)

    assert isinstance(restored, FlowPlan)
    assert dumps_toml(restored) == text
    assert restored.to_dict() == plan.to_dict()
    assert restored.plan_id == plan.plan_id
    assert restored.flow[0].content_hash == plan.flow[0].content_hash
    assert restored.flow[0].segments[0].tokens[0].surface("My life changed.") == "My"
    assert restored.flow[0].segments[0].pause_after == PauseIntent("timed", "500ms")


def test_toml_is_compact_local_and_columnar() -> None:
    plan = _plan()
    wire = to_toml_data(plan)
    text = dumps_toml(plan)
    segment = wire["flow"][0]["segment"][0]

    assert wire["schema_version"] == 7
    assert wire["hash_schema"] == FLOW_HASH_SCHEMA
    assert segment["token"]["span"] == [[0, 2], [3, 7], [8, 15]]
    assert segment["token"]["pos"] == ["PRON", "NOUN", "VERB"]
    assert segment["token"]["lemma"] == [[2, "change"]]
    assert wire["flow"][0]["segment"][1]["token"]["lemma"] == [[0, ""], [1, ""]]
    assert "token.span = [[0, 2], [3, 7], [8, 15]]" in text
    assert 'pause_after = {type = "timed", time = "500ms"}' in text
    assert "[[flow]]" in text and "[[flow.segment]]" in text
    assert "token_stream" not in text
    assert "[source]" not in text
    assert "config" not in text
    assert "segment_ids" not in text
    assert "token_indices" not in text
    assert "seconds" not in text
    assert "duration_s" not in text
    assert "language" not in segment
    assert wire["flow"][0]["segment"][1]["language"] == "fr-FR"
    assert text.count('language = "fr-FR"') == 2


def test_freeform_document_semantics_preserve_null_through_the_toml_sentinel() -> None:
    plan = _plan()
    updated = replace(
        plan,
        plan_id="",
        document=replace(plan.document, semantics={"optional": None, "nested": ["x", None]}),
    )

    text = dumps_toml(updated)
    restored = loads_toml(text)

    assert "__utterplan_null__" in text
    assert restored.document == updated.document


def test_metadata_and_warnings_do_not_change_plan_identity() -> None:
    plan = _plan()
    updated = replace(
        plan,
        producer={"name": "other", "version": "99"},
        warnings=("compiler diagnostic",),
    )
    assert updated.plan_id == plan.plan_id
    assert updated.flow[0].content_hash == plan.flow[0].content_hash
    assert loads_toml(dumps_toml(updated)).plan_id == plan.plan_id


def test_v6_model_rejects_identity_and_content_hash_mismatches() -> None:
    plan = _plan()
    wrong_identity = plan.to_dict()
    wrong_identity["language"] = "de-DE"
    with pytest.raises(PlanValidationError) as error:
        FlowPlan.from_dict(wrong_identity)
    assert error.value.code == "plan.identity"

    wrong_hash = plan.to_dict()
    wrong_hash["flow"][0]["hash"] = "sha256:" + "0" * 64
    with pytest.raises(PlanValidationError) as error:
        FlowPlan.from_dict(wrong_hash)
    assert error.value.code == "flow.hash"


def test_normal_loader_rejects_frozen_v4_toml_and_explicit_migration_requires_recompile() -> None:
    raw = V4_TOML.read_text(encoding="utf-8")
    frozen = decode_v4_toml_data(tomlkit.parse(raw).unwrap())
    before = copy.deepcopy(frozen)

    with pytest.raises(UnsupportedSchemaError) as error:
        loads_toml(raw)
    assert error.value.code == "schema.version_unsupported"
    assert frozen == before

    from utterplan.migration import migrate_plan_data

    with pytest.raises(PlanMigrationError) as migration_error:
        migrate_plan_data(migrate_v4_to_v5(frozen))
    assert migration_error.value.code == "migration.recompile_required"


def test_v4_toml_with_ambiguous_token_coordinates_fails_safely() -> None:
    wire = tomlkit.parse(V4_AMBIGUOUS_TOML.read_text(encoding="utf-8")).unwrap()
    legacy = decode_v4_toml_data(wire)
    with pytest.raises(PlanMigrationError) as error:
        migrate_v4_to_v5(legacy)
    assert error.value.code == "migration.token-coordinate-ambiguous"


def test_v5_historical_codec_remains_readable_but_current_migration_requires_source() -> None:
    import json

    from utterplan.codecs.v5_toml import dumps_v5_toml, loads_v5_toml
    from utterplan.model import LegacyFlowPlan

    legacy = json.loads(V4_JSON.read_text(encoding="utf-8"))
    historical = LegacyFlowPlan.from_dict(migrate_v4_to_v5(legacy))
    serialized = dumps_v5_toml(historical)
    restored = loads_v5_toml(serialized)

    assert historical.schema_version == 5
    assert restored.to_dict() == historical.to_dict()
    with pytest.raises(UnsupportedSchemaError) as error:
        from_toml_data(tomlkit.parse(serialized).unwrap())
    assert error.value.code == "schema.version_unsupported"

    from utterplan.migration import migrate_plan_data

    with pytest.raises(PlanMigrationError, match="Recompile") as migration_error:
        migrate_plan_data(restored.to_dict())
    assert migration_error.value.code == "migration.recompile_required"


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (datetime.date(2025, 1, 1), "date/time"),
        (float("nan"), "non-finite"),
        (float("inf"), "non-finite"),
    ],
)
def test_document_metadata_rejects_values_toml_cannot_represent(
    value: object, message: str
) -> None:
    wire = to_toml_data(_plan())
    wire["document"]["semantics"]["invalid"] = value
    with pytest.raises(PlanFormatError, match=message):
        from_toml_data(wire)


def test_invalid_toml_reports_location() -> None:
    with pytest.raises(PlanFormatError, match=r"line 2, column") as error:
        loads_toml('format = "utterplan"\nschema_version = [\n')
    assert error.value.code == "toml.invalid"


def test_unknown_root_fields_and_future_schema_are_rejected() -> None:
    wire: dict[str, Any] = to_toml_data(_plan())
    wire["extra"] = True
    with pytest.raises(PlanFormatError, match="unknown top-level TOML fields"):
        from_toml_data(wire)

    wire = to_toml_data(_plan())
    wire["schema_version"] = 8
    with pytest.raises(UnsupportedSchemaError):
        from_toml_data(wire)
