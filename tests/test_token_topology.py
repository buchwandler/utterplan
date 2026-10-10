from __future__ import annotations

from types import SimpleNamespace

import pytest

from utterplan.exceptions import PlanValidationError
from utterplan.model import TokenAnnotation
from utterplan.token_topology import (
    boundary_splits_lexical_content,
    find_boundary_conflict,
    validate_segment_token_edges,
)


@pytest.mark.parametrize(
    ("text", "position", "provider", "expected"),
    (
        ("HelloWorld", 5, "fallback", True),
        ("Hello;world", 6, "fallback", False),
        ("Hello;world", 5, "fallback", False),
        ("12:30", 2, "fallback", False),
        ("Hello;world", 6, "spacy", True),
        ("Hello—world", 5, "spacy", True),
        ("Hello", 0, "fallback", False),
        ("Hello", 5, "fallback", False),
    ),
)
def test_boundary_safety_preserves_provider_policies(
    text: str, position: int, provider: str, expected: bool
) -> None:
    token = TokenAnnotation(0, len(text), text)
    assert boundary_splits_lexical_content(position, token=token, provider=provider) is expected


def test_find_boundary_conflict_returns_token_provenance_and_coordinates() -> None:
    token = TokenAnnotation(10, 20, "HelloWorld")

    conflict = find_boundary_conflict(
        15,
        tokens=(token,),
        token_providers=("fallback",),
    )

    assert conflict is not None
    assert conflict.token_index == 0
    assert (conflict.token_start, conflict.token_end) == (10, 20)
    assert conflict.token_text == "HelloWorld"
    assert conflict.provider == "fallback"
    assert conflict.position == 15


def test_segment_edge_validation_keeps_projection_guard() -> None:
    token = TokenAnnotation(0, 5, "hello")
    segment = SimpleNamespace(id="seg-1", spoken_start=0, spoken_end=3)

    with pytest.raises(PlanValidationError) as exc_info:
        validate_segment_token_edges((segment,), (token,), ("fallback",))

    assert exc_info.value.code == "token.segment_split"
    assert "token 0 [0:5] at its end" in str(exc_info.value)


def test_segment_edge_validation_accepts_fallback_punctuation_cut() -> None:
    token = TokenAnnotation(0, 11, "Hello;world")
    left = SimpleNamespace(id="seg-left", spoken_start=0, spoken_end=6)
    right = SimpleNamespace(id="seg-right", spoken_start=6, spoken_end=11)

    validate_segment_token_edges(
        (left, right),
        (token,),
        ("fallback",),
    )
