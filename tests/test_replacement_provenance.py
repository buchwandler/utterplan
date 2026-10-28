from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from tests.compiler_helpers import CompilerTestPlanner
from utterplan import (
    FlowPlan,
    FlowSegment,
    FlowUnit,
    LegacyFlowPlan,
    LinguisticsConfig,
    PlanFormatError,
    PlannerConfig,
    ReplacementView,
    TokenView,
)
from utterplan.codecs.v5_toml import from_v5_toml_data, to_v5_toml_data
from utterplan.exceptions import PlanValidationError
from utterplan.explain import format_explanation
from utterplan.flow_projection import project_compiler_plan
from utterplan.hashing import V5_FLOW_HASH_SCHEMA


def _compile_flow(text: str) -> FlowPlan:
    config = PlannerConfig(
        language="en-us",
        linguistics=LinguisticsConfig(use_spacy=False),
    )
    compiler_plan = CompilerTestPlanner(config).plan(text)
    return project_compiler_plan(compiler_plan)


def test_art_replacement_projects_to_compact_segment_local_v5_provenance() -> None:
    compiler_plan = CompilerTestPlanner(
        PlannerConfig(language="en-us", linguistics=LinguisticsConfig(use_spacy=False))
    ).plan("Because someone (ART) thought this part could use some more verisimilitude.")
    flow = project_compiler_plan(compiler_plan)
    segment, replacement = next(
        (segment, item)
        for unit in flow.flow
        for segment in unit.segments
        for item in segment.replacements
        if item.source == "ART"
    )

    assert replacement.surface(segment.text) == "A R T"
    assert segment.text[replacement.start : replacement.end] == "A R T"
    toml = flow.to_toml()
    assert f"replacement.span = [[{replacement.start}, {replacement.end}]]" in toml
    assert 'replacement.source = ["ART"]' in toml

    restored = FlowPlan.from_toml(toml)
    restored_segment, restored_replacement = next(
        (segment, item)
        for unit in restored.flow
        for segment in unit.segments
        for item in segment.replacements
    )
    assert restored_replacement == replacement
    assert restored_replacement.surface(restored_segment.text) == "A R T"
    assert f'[{replacement.start}:{replacement.end}] "A R T" <- "ART"' in format_explanation(
        restored
    )

    example = FlowPlan(
        language="en-us",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        "Because someone (A R T) thought this part could use some more verisimilitude.",
                        "en-us",
                        replacements=(ReplacementView(17, 22, "ART"),),
                    ),
                )
            ),
        ),
    )
    example_toml = example.to_toml()
    assert "replacement.span = [[17, 22]]" in example_toml
    assert 'replacement.source = ["ART"]' in example_toml


def test_multiple_replacements_keep_ordered_parallel_columns_and_round_trip() -> None:
    flow = _compile_flow("Dr. bought 5 kg.")
    segment = flow.flow[0].segments[0]
    replacements = segment.replacements

    assert len(replacements) == 2
    assert list(replacements) == sorted(
        replacements, key=lambda item: (item.start, item.end, item.source)
    )
    assert [segment.text[item.start : item.end] for item in replacements] == [
        "Doctor",
        "five kilograms",
    ]
    assert [item.source for item in replacements] == ["Dr.", "5 kg"]

    wire = FlowPlan.from_toml(flow.to_toml()).to_dict()
    wire_segment = wire["flow"][0]["segments"][0]
    assert wire_segment["replacements"] == [item.to_dict() for item in replacements]


def test_malformed_or_unlocalizable_replacement_provenance_is_rejected() -> None:
    source_plan = CompilerTestPlanner(
        PlannerConfig(language="en-us", linguistics=LinguisticsConfig(use_spacy=False))
    ).plan("(ART)")
    malformed = {**source_plan.preparation.replacements[0], "kind": ""}
    preparation = replace(source_plan.preparation, replacements=(malformed,))
    with pytest.raises(PlanValidationError, match="replacement kind/rule"):
        project_compiler_plan(replace(source_plan, preparation=preparation))

    split_plan = CompilerTestPlanner(
        PlannerConfig(
            language="en-us",
            linguistics=LinguisticsConfig(use_spacy=False),
        )
    ).plan("Alpha. Beta.")
    crossing = {
        "output_start": 4,
        "output_end": 8,
        "source_start": 4,
        "source_end": 8,
        "source": "a. B",
        "replacement": "a. B",
    }
    preparation = replace(split_plan.preparation, replacements=(crossing,))
    with pytest.raises(PlanValidationError, match="exactly one owning segment"):
        project_compiler_plan(replace(split_plan, preparation=preparation))


def test_character_spelling_split_keeps_replacement_provenance_segment_local() -> None:
    compiler_plan = CompilerTestPlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
            linguistics=LinguisticsConfig(use_spacy=False),
        )
    ).plan("[ART's]{sub=\"A R T's\"} house is nice.")
    flow = project_compiler_plan(compiler_plan)
    localized = [
        (segment, replacement)
        for unit in flow.flow
        for segment in unit.segments
        for replacement in segment.replacements
    ]

    assert len(localized) == 2
    assert [
        (segment.text[replacement.start : replacement.end], replacement.source)
        for segment, replacement in localized
    ] == [("A R T", "ART's"), ("'s", "ART's")]


def test_replacement_view_and_flow_segment_validate_local_spans() -> None:
    with pytest.raises(ValueError, match="coordinates must be integers"):
        ReplacementView(True, 1, "source")
    with pytest.raises(ValueError, match="non-negative"):
        ReplacementView(2, 1, "source")
    with pytest.raises(ValueError, match="non-empty string"):
        ReplacementView(0, 1, "source", kind="")
    with pytest.raises(ValueError, match="outside segment text"):
        FlowSegment("short", "en-us", replacements=(ReplacementView(0, 6, "source"),))


def test_v5_replacement_columns_reject_invalid_cardinality_bounds_and_sparse_indexes() -> None:
    flow = _compile_flow("Dr. bought 5 kg.")
    v5_flow = LegacyFlowPlan(
        language=flow.language,
        unit="paragraph",
        flow=tuple(
            FlowUnit(
                tuple(
                    replace(segment, boundary_before=(), boundary_after=())
                    for segment in unit.segments
                )
            )
            for unit in flow.flow
        ),
        document=flow.document,
        linguistics=flow.linguistics,
        producer=flow.producer,
        warnings=flow.warnings,
        schema_version=5,
        hash_schema=V5_FLOW_HASH_SCHEMA,
    )
    base = to_v5_toml_data(v5_flow)

    invalid_bounds = deepcopy(base)
    segment = next(item for item in invalid_bounds["flow"][0]["segment"] if "replacement" in item)
    segment["replacement"]["span"][0][1] = len(segment["text"]) + 1
    with pytest.raises(PlanFormatError, match="replacement span"):
        from_v5_toml_data(invalid_bounds)

    invalid_cardinality = deepcopy(base)
    segment = next(
        item for item in invalid_cardinality["flow"][0]["segment"] if "replacement" in item
    )
    segment["replacement"]["source"].pop()
    with pytest.raises(PlanFormatError, match="equal lengths"):
        from_v5_toml_data(invalid_cardinality)

    invalid_sparse_index = deepcopy(base)
    segment = next(
        item for item in invalid_sparse_index["flow"][0]["segment"] if "replacement" in item
    )
    count = len(segment["replacement"]["span"])
    segment["replacement"]["kind"] = [[count, "abbreviation"]]
    with pytest.raises(PlanFormatError, match="sparse replacement indices"):
        from_v5_toml_data(invalid_sparse_index)


def test_replacement_provenance_does_not_change_hashes_but_token_semantics_do() -> None:
    token = TokenView(
        0,
        4,
        lemma="live",
        pos="VERB",
        tag="VBP",
        morph="Tense=Pres|VerbForm=Fin",
    )
    segment = FlowSegment(
        "live",
        "en-us",
        tokens=(token,),
        replacements=(ReplacementView(0, 4, "LIVE", kind="structured", rule="rule-a"),),
    )
    plan = FlowPlan(language="en-us", flow=(FlowUnit((segment,)),))

    changed_replacement = replace(
        segment.replacements[0], source="other", kind="abbreviation", rule="rule-b"
    )
    provenance_only = replace(
        plan,
        flow=(FlowUnit((replace(segment, replacements=(changed_replacement,)),)),),
        plan_id="",
    )
    assert provenance_only.flow[0].content_hash == plan.flow[0].content_hash
    assert provenance_only.plan_id == plan.plan_id

    changed_token = replace(token, pos="ADJ", tag="JJ")
    linguistic_change = replace(
        plan,
        flow=(FlowUnit((replace(segment, tokens=(changed_token,)),)),),
        plan_id="",
    )
    assert linguistic_change.flow[0].content_hash != plan.flow[0].content_hash
    assert linguistic_change.plan_id != plan.plan_id
