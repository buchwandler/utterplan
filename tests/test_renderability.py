from __future__ import annotations

from dataclasses import replace

import pytest

from utterplan import (
    ConfigurationError,
    PlannerConfig,
    PlanRenderabilityError,
    PlanSegment,
    PlanValidationError,
    TokenAnnotation,
    UtterancePlan,
    UtterancePlanner,
    classify_segment,
    contains_speech_content,
)
from utterplan.parsers import ParsedDocument, SourceTextSpan, map_structural_span_to_source
from utterplan.units import make_units


def _segment(text: str, *, start: int = 0, end: int | None = None) -> PlanSegment:
    return PlanSegment(
        id="seg-000000",
        text=text,
        spoken_start=start,
        spoken_end=start + len(text) if end is None else end,
        language="en-US",
        structural_start=start,
        structural_end=start + len(text) if end is None else end,
    )


def test_unicode_letters_and_numbers_are_speech_content() -> None:
    for value in ("Überraschung", "你好", "مرحبا", "2026"):
        assert contains_speech_content(value)
        assert classify_segment(_segment(value), 0) is None



def test_planner_returns_plans_for_unicode_lexical_text() -> None:
    for value in ("Überraschung", "你好", "مرحبا", "2026"):
        plan = UtterancePlanner(
            PlannerConfig(language="en-US", text_preparation="identity")
        ).plan(value)
        assert plan.segments
        assert plan.document_metadata["planning"]["renderability"]["guaranteed"] is True


def test_strict_preflight_reports_every_failure_in_source_order() -> None:
    source = "First.\n\n.\n\n?\n\nLast."
    planner = UtterancePlanner(
        PlannerConfig(language="en-US", text_preparation="identity")
    )

    with pytest.raises(PlanRenderabilityError) as error:
        planner.plan(source)

    assert [issue.reason for issue in error.value.issues] == [
        "punctuation_only",
        "punctuation_only",
    ]
    assert [issue.line for issue in error.value.issues] == [3, 5]
    assert [issue.source_start for issue in error.value.issues] == sorted(
        issue.source_start for issue in error.value.issues if issue.source_start is not None
    )
    assert error.value.mode == "strict"


def test_renderability_mode_is_validated_and_participates_in_plan_identity() -> None:
    with pytest.raises(ConfigurationError, match="renderability_mode"):
        PlannerConfig(language="en-US", renderability_mode="disabled")  # type: ignore[arg-type]

    strict = UtterancePlanner(PlannerConfig(language="en-US")).plan("Hello.")
    repair = UtterancePlanner(
        PlannerConfig(language="en-US", renderability_mode="repair")
    ).plan("Hello.")
    assert strict.plan_id != repair.plan_id
    assert strict.config["renderability_mode"] == "strict"
    assert repair.config["renderability_mode"] == "repair"


def test_ssmd_source_text_spans_map_an_issue_to_original_markup_location() -> None:
    source = '---\nssmd_version: "0.9"\n---\nHello\n.'
    body_start = source.index("Hello")
    period_start = source.rfind(".")
    parsed = ParsedDocument(
        source_text=source,
        structural_text="Hello\n.",
        text_spans=(
            SourceTextSpan(0, 6, body_start, body_start + 6),
            SourceTextSpan(6, 7, period_start, period_start + 1),
        ),
    )

    issue = classify_segment(_segment(".", start=6, end=7), 0, parsed=parsed)

    assert issue is not None
    assert (issue.source_start, issue.source_end) == (period_start, period_start + 1)
    assert (issue.line, issue.column) == (5, 1)
    assert issue.source_excerpt == "."


def test_missing_nonidentity_source_map_does_not_invent_coordinates() -> None:
    parsed = ParsedDocument(source_text="markup", structural_text="clean")
    assert map_structural_span_to_source(parsed, 0, 1) == (None, None)


def test_spokenform_offsets_map_later_renderability_issue_back_to_source() -> None:
    source = "Dr. Smith.\n\n.\n\nWorld."
    planner = UtterancePlanner(PlannerConfig(language="en-US"))

    with pytest.raises(PlanRenderabilityError) as error:
        planner.plan(source)

    issue = error.value.issues[0]
    assert issue.line == 3 and issue.column == 1
    assert source[issue.source_start : issue.source_end] == "."
    assert issue.spoken_start > issue.source_start

def test_punctuation_whitespace_empty_and_symbols_have_stable_issue_codes() -> None:
    cases = (
        (".", "renderability.punctuation_only"),
        ("  \t", "renderability.whitespace_only"),
        ("", "renderability.empty"),
        ("€", "renderability.symbol_only"),
        ("🙂", "renderability.symbol_only"),
        ("∑", "renderability.symbol_only"),
    )
    for text, expected_code in cases:
        issue = classify_segment(_segment(text), 0)
        assert issue is not None
        assert issue.code == expected_code


def test_issue_contains_token_diagnostics_and_original_source_location() -> None:
    source = "front matter\nbody .\nlast"
    parsed = ParsedDocument(
        source_text=source,
        structural_text="body .\nlast",
        text_spans=(
            SourceTextSpan(0, 5, 13, 18),
            SourceTextSpan(5, 6, 18, 19),
            SourceTextSpan(6, 11, 19, 24),
        ),
    )
    segment = _segment(".", start=5, end=6)
    tokens = (TokenAnnotation(5, 6, ".", pos="PUNCT", id="token-punct"),)
    segment = replace(segment, token_indices=(0,))

    issue = classify_segment(segment, 3, tokens, parsed=parsed)

    assert issue is not None
    assert issue.segment_index == 3
    assert issue.token_pos == ("PUNCT",)
    assert issue.token_ids == ("token-punct",)
    assert (issue.structural_start, issue.structural_end) == (5, 6)
    assert (issue.source_start, issue.source_end) == (18, 19)
    assert (issue.line, issue.column, issue.end_line, issue.end_column) == (2, 6, 2, 7)
    assert issue.source_excerpt == "body ."


def test_renderability_error_preserves_issues_mode_and_summary() -> None:
    first = classify_segment(_segment("."), 0)
    second = classify_segment(_segment("€"), 1)
    assert first is not None and second is not None

    error = PlanRenderabilityError((first, second), mode="strict")

    assert error.code == "plan.not_renderable"
    assert error.issues == (first, second)
    assert error.mode == "strict"
    assert "2 renderer segments" in str(error)
    assert "seg-000000" in str(error)


def test_schema_v3_loading_rejects_punctuation_only_renderer_segment() -> None:
    plan = UtterancePlanner(
        PlannerConfig(language="en-US", text_preparation="identity")
    ).plan("Hello.")
    original = plan.segments[0]
    invalid_segment = replace(
        original,
        text=".",
        spoken_start=5,
        spoken_end=6,
        structural_start=5,
        structural_end=6,
        token_indices=(),
        annotation_ids=(),
    )
    invalid_plan = replace(
        plan,
        segments=(invalid_segment,),
        units=make_units((invalid_segment,), plan.markers, plan.tokens, "paragraph"),
    ).with_identity()

    with pytest.raises(PlanValidationError) as error:
        UtterancePlan.from_dict(invalid_plan.to_dict())

    assert error.value.code == "segment.not_renderable"
    assert error.value.path == "$.segments[0]"
