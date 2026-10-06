from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace

import pytest

from utterplan import (
    PlannerConfig,
    PlanValidationError,
    SemanticBoundary,
    UtterancePlan,
    UtterancePlanner,
)
from utterplan.units import make_units


def _plan_with(boundaries: tuple[SemanticBoundary, ...]) -> UtterancePlan:
    plan = UtterancePlanner(PlannerConfig(language="en-us", text_preparation="identity")).plan(
        "Alpha beta gamma delta."
    )
    units = make_units(
        plan.segments,
        plan.markers,
        plan.tokens,
        str(plan.config["unit"]),
        boundaries,
    )
    return replace(plan, semantic_boundaries=boundaries, units=units).with_identity()


def test_semantic_boundary_is_public_immutable_type() -> None:
    boundary = SemanticBoundary("semantic-boundary-000000", 6, "clause")

    field_name = "position"
    assert boundary.spoken_position == boundary.position
    with pytest.raises(FrozenInstanceError):
        setattr(boundary, field_name, 7)


def test_semantic_boundary_roundtrip_and_attrs_are_plain_json() -> None:
    boundary = SemanticBoundary(
        "semantic-boundary-000000",
        6,
        "vendor_future_kind",
        origin="analysis-provider",
        language_run_id="lang-0",
        attrs={"diagnostic": {"raw": [5, 6]}, "enabled": True},
    )
    plan = _plan_with((boundary,))

    serialized = plan.to_dict()
    assert serialized["semantic_boundaries"] == [boundary.to_dict()]
    assert UtterancePlan.from_toml(plan.to_toml()) == plan
    assert json.loads(json.dumps(boundary.to_dict())) == boundary.to_dict()
    assert serialized["semantic_boundaries"][0]["kind"] == "vendor_future_kind"


def test_semantic_boundary_position_splits_spoken_text_losslessly() -> None:
    boundary = SemanticBoundary("semantic-boundary-000000", 6, "clause")
    plan = _plan_with((boundary,))

    left = plan.texts.spoken[: boundary.position]
    right = plan.texts.spoken[boundary.position :]
    assert left + right == plan.texts.spoken


def test_semantic_boundary_does_not_require_a_pause_event() -> None:
    boundary = SemanticBoundary("semantic-boundary-000000", 6, "clause")
    plan = replace(_plan_with((boundary,)), boundaries=()).with_identity()

    plan.validate()
    assert plan.semantic_boundaries == (boundary,)
    assert plan.boundaries == ()


def test_semantic_boundaries_in_range_filters_kind_sorts_and_excludes_endpoints() -> None:
    plan = _plan_with(
        (
            SemanticBoundary("semantic-boundary-000002", 12, "clause"),
            SemanticBoundary("semantic-boundary-000001", 6, "sentence"),
            SemanticBoundary("semantic-boundary-000003", 18, "paragraph"),
        )
    )

    selected = plan.semantic_boundaries_in_range(6, 18, kinds=("clause", "paragraph"))
    assert [item.position for item in selected] == [12]
    inclusive = plan.semantic_boundaries_in_range(6, 18, interior_only=False)
    assert [item.position for item in inclusive] == [6, 12, 18]
    assert plan.semantic_boundaries_in_range(6, 18, kinds=("unknown",)) == ()


def test_semantic_boundaries_for_segment_returns_interior_absolute_positions() -> None:
    plan = _plan_with(
        (
            SemanticBoundary("semantic-boundary-000000", 6, "clause"),
            SemanticBoundary("semantic-boundary-000001", 12, "parenthetical"),
        )
    )
    segment = plan.segments[0]

    result = plan.semantic_boundaries_for_segment(segment.id, kinds=("clause", "parenthetical"))
    assert result == plan.semantic_boundaries
    assert all(segment.spoken_start < item.position < segment.spoken_end for item in result)


def test_semantic_boundary_out_of_range_is_rejected() -> None:
    plan = _plan_with((SemanticBoundary("semantic-boundary-000000", 999, "sentence"),))

    with pytest.raises(PlanValidationError) as error:
        plan.validate()

    assert error.value.code == "semantic_boundary.out_of_range"
    assert error.value.path == "$.semantic_boundaries[0].position"


def test_semantic_boundary_unknown_language_run_is_rejected() -> None:
    plan = _plan_with(
        (
            SemanticBoundary(
                "semantic-boundary-000000",
                6,
                "sentence",
                language_run_id="missing-language-run",
            ),
        )
    )

    with pytest.raises(PlanValidationError) as error:
        plan.validate()

    assert error.value.code == "semantic_boundary.unknown_language_run"
    assert error.value.path == "$.semantic_boundaries[0].language_run_id"


def test_semantic_boundary_duplicate_kind_position_is_rejected() -> None:
    plan = replace(
        _plan_with(()),
        semantic_boundaries=(
            SemanticBoundary("semantic-boundary-000000", 6, "sentence"),
            SemanticBoundary("semantic-boundary-000001", 6, "sentence"),
        ),
    )

    with pytest.raises(PlanValidationError, match="semantic_boundary.duplicate"):
        plan.validate()


def test_semantic_boundaries_must_be_canonically_ordered() -> None:
    plan = _plan_with(
        (
            SemanticBoundary("semantic-boundary-000001", 12, "sentence"),
            SemanticBoundary("semantic-boundary-000000", 6, "sentence"),
        )
    )

    with pytest.raises(PlanValidationError, match="semantic_boundary.order"):
        plan.validate()


def test_semantic_boundary_ids_are_globally_unique() -> None:
    plan = _plan_with(
        (
            SemanticBoundary("semantic-boundary-000000", 6, "sentence"),
            SemanticBoundary("semantic-boundary-000000", 12, "sentence"),
        )
    )

    with pytest.raises(PlanValidationError) as error:
        plan.validate()
    assert error.value.code == "id.duplicate"


def test_clause_semantic_boundaries_must_be_interior() -> None:
    plan = _plan_with((SemanticBoundary("semantic-boundary-000000", 0, "clause"),))

    with pytest.raises(PlanValidationError, match="semantic_boundary.not_interior"):
        plan.validate()


def test_semantic_boundary_attrs_must_be_json_compatible() -> None:
    plan = replace(
        _plan_with(()),
        semantic_boundaries=(
            SemanticBoundary(
                "semantic-boundary-000000",
                6,
                "sentence",
                attrs={"unsupported": object()},
            ),
        ),
    )

    with pytest.raises(PlanValidationError, match="semantic_boundary.attrs"):
        plan.validate()
