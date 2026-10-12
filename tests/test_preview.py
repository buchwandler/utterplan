from __future__ import annotations

import pytest

from utterplan import (
    FlowPlan,
    FlowSegment,
    FlowUnit,
    PauseIntent,
    ReplacementView,
    TokenView,
    preview_plan,
    resolve_segment_selector,
)


def _plan(*units: tuple[FlowSegment, ...]) -> FlowPlan:
    return FlowPlan(
        language="en-US",
        flow=tuple(FlowUnit(unit) for unit in units),
    )


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("12", {12}),
        ("23-26", {23, 24, 25, 26}),
        ("1,3-5", {1, 3, 4, 5}),
        ("all", None),
    ],
)
def test_segment_selector_resolves_zero_based_indexes(
    selector: str, expected: frozenset[int] | set[int] | None
) -> None:
    actual = resolve_segment_selector(selector, 40)
    assert actual == (frozenset(expected) if expected is not None else None)


@pytest.mark.parametrize("selector", ["0-", "3-1", "foo", "1,,2", "4"])
def test_segment_selector_rejects_malformed_and_out_of_range_values(selector: str) -> None:
    with pytest.raises(ValueError):
        resolve_segment_selector(selector, 4)


def test_sentence_selection_expands_to_complete_containing_chunk() -> None:
    plan = _plan(
        (
            FlowSegment("A", "en-US"),
            FlowSegment("B", "en-US"),
            FlowSegment("C.", "en-US", boundary_after=("sentence",)),
        )
    )

    chunks = preview_plan(plan, segments="1", chunk_by="sentence")

    assert len(chunks) == 1
    assert chunks[0].text == "ABC."
    assert [item.global_index for item in chunks[0].segments] == [0, 1, 2]


def test_chunk_modes_respect_saved_edges_and_paragraph_flow_units() -> None:
    plan = _plan(
        (
            FlowSegment("A", "en-US", boundary_after=("clause",)),
            FlowSegment("B", "en-US", boundary_after=("sentence",)),
            FlowSegment("C", "en-US"),
        ),
        (FlowSegment("D", "en-US"),),
    )

    assert [chunk.text for chunk in preview_plan(plan, chunk_by="segment")] == [
        "A",
        "B",
        "C",
        "D",
    ]
    assert [chunk.text for chunk in preview_plan(plan, chunk_by="clause")] == [
        "A",
        "B",
        "C",
        "D",
    ]
    assert [chunk.text for chunk in preview_plan(plan, chunk_by="sentence")] == [
        "AB",
        "C",
        "D",
    ]
    assert [chunk.text for chunk in preview_plan(plan, chunk_by="paragraph")] == [
        "ABC",
        "D",
    ]
    assert preview_plan(plan, segments="0", chunk_by="sentence")[0].text == "AB"


def test_pause_policies_only_change_pause_projection_and_never_mutate_plan() -> None:
    plan = _plan(
        (
            FlowSegment(
                "A",
                "en-US",
                boundary_after=("clause",),
                tokens=(TokenView(0, 1, lemma="a"),),
                replacements=(ReplacementView(0, 1, "A", kind="ssmd-sub"),),
            ),
            FlowSegment(
                "B",
                "en-US",
                pause_after=PauseIntent("timed", "500ms"),
                boundary_after=("sentence",),
            ),
            FlowSegment("C", "en-US", pause_after=PauseIntent("none"), boundary_after=("clause",)),
            FlowSegment("D", "en-US"),
        )
    )
    before = plan.to_toml()
    plan_id = plan.plan_id

    native = preview_plan(plan, chunk_by="clause", pause_policy="native")
    automatic = preview_plan(plan, chunk_by="clause", pause_policy="automatic")
    manual = preview_plan(plan, chunk_by="clause", pause_policy="manual")

    assert [chunk.text for chunk in native] == ["A", "B", "C", "D"]
    assert [chunk.text for chunk in automatic] == [chunk.text for chunk in native]
    assert [chunk.text for chunk in manual] == [chunk.text for chunk in native]
    assert [chunk.automatic_pause for chunk in native] == [None, None, None, None]
    assert [chunk.automatic_pause for chunk in automatic] == ["clause", None, None, "sentence"]
    assert [chunk.automatic_pause for chunk in manual] == ["clause", "sentence", None, "sentence"]
    assert manual[1].authored_pause_after == PauseIntent("timed", "500ms")
    assert manual[2].authored_pause_after == PauseIntent("none")
    assert native[0].segments == automatic[0].segments == manual[0].segments
    assert plan.to_toml() == before
    assert plan.plan_id == plan_id
    assert plan.flow[0].segments[0].tokens[0].start == 0
    assert plan.flow[0].segments[0].replacements[0].start == 0


def test_preview_json_data_is_stable_and_preserves_authored_pause_shape() -> None:
    plan = _plan((FlowSegment("Ready.", "en-US", pause_after=PauseIntent("timed", "500ms")),))

    chunk = preview_plan(plan, pause_policy="manual")[0]
    value = chunk.to_dict()

    assert value == {
        "index": 0,
        "text": "Ready.",
        "segments": [{"global_index": 0, "unit_index": 0, "local_index": 0}],
        "boundary_before": [],
        "boundary_after": [],
        "authored_pause_before": None,
        "authored_pause_after": {"type": "timed", "time": "500ms"},
        "automatic_pause": "sentence",
    }


def test_preview_rejects_unknown_modes_and_pause_policies() -> None:
    plan = _plan((FlowSegment("Hello.", "en-US"),))
    with pytest.raises(ValueError, match="chunk mode"):
        preview_plan(plan, chunk_by="comma")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="pause policy"):
        preview_plan(plan, pause_policy="tts")  # type: ignore[arg-type]
