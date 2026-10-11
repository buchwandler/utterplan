from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any, Literal

import pytest

from utterplan import LinguisticsConfig, PlannerConfig, UtterancePlanner
from utterplan.exceptions import PlanValidationError
from utterplan.model import TokenAnnotation
from utterplan.segmentation import CutCandidate, reconcile_cut_candidates


def _set_phrasplit(monkeypatch: pytest.MonkeyPatch, splitter: Any) -> None:
    monkeypatch.setitem(
        sys.modules,
        "phrasplit",
        SimpleNamespace(split_with_offsets=splitter),
    )


def _config(mode: Literal["strict", "repair"]) -> PlannerConfig:
    return PlannerConfig(
        language="en-US",
        text_preparation="identity",
        linguistics=LinguisticsConfig(use_spacy=False),
        renderability_mode=mode,  # type: ignore[arg-type]
    )


def _segment_surfaces(plan: Any) -> list[str]:
    return [segment.text for unit in plan.flow for segment in unit.segments]


@pytest.mark.parametrize("mode", ("strict", "repair"))
def test_phrasplit_failure_recovers_and_preserves_sentence_topology_in_both_modes(
    monkeypatch: pytest.MonkeyPatch, mode: Literal["strict", "repair"]
) -> None:
    def broken(_text: str, **_kwargs: Any) -> None:
        raise TypeError("dependency call failed")

    _set_phrasplit(monkeypatch, broken)
    text = "Hello. World."
    planner = UtterancePlanner(_config(mode))
    try:
        result = planner.compile(text)
    finally:
        planner.close()

    assert _segment_surfaces(result.plan) == ["Hello.", "World."]
    assert "".join(_segment_surfaces(result.plan)) == text.replace(" ", "")
    diagnostic = next(
        item for item in result.diagnostics if item.code == "segmentation.phrasplit_failed"
    )
    assert diagnostic.severity == "warning"


def test_malformed_phrasplit_batch_is_discarded_without_losing_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def malformed(_text: str, **_kwargs: Any) -> list[Any]:
        return [SimpleNamespace(char_start=0, char_end=5, text="lost!")]

    _set_phrasplit(monkeypatch, malformed)
    text = "Hello. World."
    planner = UtterancePlanner(_config("strict"))
    try:
        result = planner.compile(text)
    finally:
        planner.close()

    surfaces = _segment_surfaces(result.plan)
    assert "".join(surfaces).replace(" ", "") == text.replace(" ", "")
    assert [
        item.message for item in result.diagnostics if item.code == "segmentation.phrasplit_invalid"
    ]


def test_unsafe_automatic_boundary_is_merged_before_successful_attempt_projects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def split_inside_token(text: str, **_kwargs: Any) -> list[Any]:
        return [
            SimpleNamespace(char_start=0, char_end=4, text=text[:4]),
            SimpleNamespace(char_start=4, char_end=len(text), text=text[4:]),
        ]

    _set_phrasplit(monkeypatch, split_inside_token)
    text = "lifecycle now"
    planner = UtterancePlanner(_config("strict"))
    try:
        attempt = planner.compile_attempt(text)
        assert attempt.ok
        # Projection is part of the success contract, not a downstream surprise.
        from utterplan.flow_projection import project_compiler_plan

        flow = project_compiler_plan(attempt.candidate.to_plan())
    finally:
        planner.close()

    assert _segment_surfaces(flow) == [text]
    assert any(item.code == "segmentation.lexical_boundary_merged" for item in attempt.diagnostics)


def test_punctuation_only_paragraph_is_preserved_for_renderability() -> None:
    planner = UtterancePlanner(_config("strict"))
    try:
        attempt = planner.compile_attempt("Hello.\n\n!!!\n\nWorld.")
    finally:
        planner.close()

    assert not attempt.ok
    assert any(
        issue.code == "renderability.punctuation_only" for issue in attempt.renderability.issues
    )
    assert any(segment.text == "!!!" for segment in attempt.candidate.segments)


@pytest.mark.parametrize(
    ("cut", "token_start", "token_end"),
    ((5588, 5585, 5591), (4539, 4533, 4541)),
)
def test_optional_reported_cut_geometries_merge_before_segment_construction(
    cut: int, token_start: int, token_end: int
) -> None:
    text = "x" * token_start + "abcdefgh"[: token_end - token_start] + " tail"
    token_text = text[token_start:token_end]
    token = TokenAnnotation(token_start, token_end, token_text, language="en-US")
    candidate = CutCandidate(cut, "phrasplit", semantic_kind="sentence", hardness="soft")

    accepted, repairs, conflicts = reconcile_cut_candidates(
        text, (candidate,), tokens=(token,), token_providers=("fallback",)
    )

    assert accepted == ()
    assert conflicts == ()
    assert len(repairs) == 1
    assert repairs[0].code == "segmentation.cut_merged"
    assert repairs[0].original_position == cut
    assert repairs[0].spoken_start == token_start
    assert repairs[0].spoken_end == token_end


def test_optional_cut_inside_atomic_substitution_is_dropped_but_hard_cut_is_actionable() -> None:
    candidate = CutCandidate(2, "phrasplit", hardness="soft")
    accepted, repairs, conflicts = reconcile_cut_candidates(
        "A R T", (candidate,), tokens=(), token_providers=(), protected_ranges=((0, 5),)
    )

    assert accepted == ()
    assert conflicts == ()
    assert repairs[0].code == "segmentation.atomic_boundary_dropped"
    with pytest.raises(PlanValidationError) as error:
        reconcile_cut_candidates(
            "A R T",
            (CutCandidate(2, "authored_pause", hardness="hard"),),
            tokens=(),
            token_providers=(),
            protected_ranges=((0, 5),),
        )
    assert error.value.code == "segmentation.atomic_hard_cut_conflict"
