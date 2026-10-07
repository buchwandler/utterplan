from __future__ import annotations

from dataclasses import replace

import pytest

from utterplan import (
    AnnotationSpan,
    BoundaryEvent,
    EmphasisDirective,
    PlanFormatError,
    PlannerConfig,
    PlanRenderabilityError,
    PlanSegment,
    SegmentDirectives,
    SemanticBoundary,
    UtterancePlan,
    UtterancePlanner,
    assess_renderability_repair,
    classify_segment,
    compile_attempt,
)
from utterplan.config import PauseConfig
from utterplan.planner import _repair_renderer_segments


def _segment(
    segment_id: str,
    text: str,
    start: int,
    end: int,
    *,
    language: str = "en-US",
) -> PlanSegment:
    return PlanSegment(
        id=segment_id,
        text=text,
        spoken_start=start,
        spoken_end=end,
        language=language,
        structural_start=start,
        structural_end=end,
    )


def _punctuation_issue(segment: PlanSegment, index: int = 1):
    issue = classify_segment(segment, index)
    assert issue is not None
    assert issue.code == "renderability.punctuation_only"
    return issue


def _assess(
    segments: list[PlanSegment],
    issue,
    text: str,
    *,
    boundaries: tuple[BoundaryEvent, ...] = (),
    annotations: tuple[AnnotationSpan, ...] = (),
    semantic_boundaries: tuple[SemanticBoundary, ...] = (),
):
    assessment = assess_renderability_repair(
        issue,
        segments[issue.segment_index],
        segments,
        spoken_text=text,
        boundaries=boundaries,
        pause_config=PauseConfig(),
        annotations=annotations,
        semantic_boundaries=semantic_boundaries,
    )
    return replace(issue, repair_assessment=assessment)


def test_repair_is_the_default_and_records_a_source_located_guarantee() -> None:
    config = PlannerConfig(language="en-US", text_preparation="identity")
    plan = UtterancePlanner(config).plan("Hello.\n\n.\n\nWorld.")
    repeated = UtterancePlanner(config).plan("Hello.\n\n.\n\nWorld.")

    assert config.renderability_mode == "repair"
    assert repeated.plan_id == plan.plan_id
    assert repeated.to_toml() == plan.to_toml()
    assert [segment.text for segment in plan.segments] == ["Hello.", "World."]
    assert plan.document_metadata["planning"]["renderability"] == {
        "mode": "repair",
        "checked_segments": 3,
        "repair_count": 1,
        "guaranteed": True,
    }
    repairs = [item for item in plan.diagnostics if item.code == "planning.renderability.repaired"]
    assert len(repairs) == 1
    assert "by removing the punctuation-only segment" in repairs[0].message
    assert repairs[0].line == 3
    assert plan.texts.spoken == "Hello.\n\n.\n\nWorld."


def test_default_repairs_exact_comma_space_with_isolated_planner_topology(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import utterplan.planner as planner_module

    def split_around_comma_space(text: str, *_args, **_kwargs) -> list[PlanSegment]:
        start = text.index(",")
        end = start + 2
        return [
            _segment("seg-000000", text[:start], 0, start),
            _segment("seg-000001", text[start:end], start, end),
            _segment("seg-000002", text[end:], end, len(text)),
        ]

    monkeypatch.setattr(planner_module, "_segment", split_around_comma_space)
    source = "Before, after"
    config = PlannerConfig(language="en-US", text_preparation="identity")
    plan = UtterancePlanner(config).plan(source)

    assert plan.document_metadata["planning"]["renderability"]["guaranteed"] is True
    assert plan.segments[1].text == ", after"
    repaired = [item for item in plan.diagnostics if item.code == "planning.renderability.repaired"]
    assert len(repaired) == 1
    assert "', '" in repaired[0].message

    strict = UtterancePlanner(replace(config, renderability_mode="strict"))
    with pytest.raises(PlanRenderabilityError) as error:
        strict.plan(source)
    issue = error.value.issues[0]
    assert issue.text == ", "
    assert issue.repair_assessment is not None
    assert issue.repair_assessment.safe is True
    assert issue.repair_assessment.action == "merge_next"
    assert "Automatic repair: safe; merge with the following spoken segment." in str(error.value)
    assert "Spoken context:" in str(error.value)


def test_safe_merge_uses_assessed_action_and_canonical_text() -> None:
    lexical = _segment("seg-000000", "Hello", 0, 5)
    punctuation = _segment("seg-000001", ".", 5, 6)
    segments = [lexical, punctuation]
    issue = _assess(segments, _punctuation_issue(punctuation), "Hello.")

    assert issue.repair_assessment is not None
    assert issue.repair_assessment.action == "merge_previous"
    assert issue.repair_assessment.safe is True
    repaired, repairs = _repair_renderer_segments(segments, (issue,), "Hello.")

    assert len(repaired) == 1
    assert repaired[0].text == "Hello."
    assert (repaired[0].spoken_start, repaired[0].spoken_end) == (0, 6)
    assert repairs[0].repair == "merge_neutral_punctuation"
    assert classify_segment(repaired[0], 0) is None


def test_active_pause_at_join_blocks_merge_but_preserves_safe_drop() -> None:
    lexical = _segment("seg-000000", "Hello", 0, 5)
    punctuation = _segment("seg-000001", ".", 5, 6)
    boundary = BoundaryEvent(
        id="boundary-000000",
        position=5,
        kind="explicit",
        seconds=0.5,
        origin="ssmd",
        strength="sentence",
    )
    segments = [lexical, punctuation]
    issue = _assess(
        segments,
        _punctuation_issue(punctuation),
        "Hello.",
        boundaries=(boundary,),
    )

    assert issue.repair_assessment is not None
    assert issue.repair_assessment.safe is True
    assert issue.repair_assessment.action == "drop"
    assert "active pause at spoken position 5" in issue.repair_assessment.blockers
    repaired, repairs = _repair_renderer_segments(segments, (issue,), "Hello.")
    assert [segment.text for segment in repaired] == ["Hello"]
    assert repairs[0].repair == "drop_non_speech_punctuation"
    assert (boundary.position, boundary.seconds) == (5, 0.5)


def test_active_pause_inside_punctuation_blocks_merge_and_drop() -> None:
    punctuation = _segment("seg-000001", "?!", 5, 7)
    boundary = BoundaryEvent(
        id="boundary-inside",
        position=6,
        kind="explicit",
        seconds=0.5,
        origin="ssmd",
        strength="sentence",
    )
    segments = [punctuation]
    issue = _assess(
        segments,
        _punctuation_issue(punctuation, index=0),
        "Hello?!",
        boundaries=(boundary,),
    )

    assert issue.repair_assessment is not None
    assert issue.repair_assessment.safe is False
    assert "active pause at spoken position 6" in issue.repair_assessment.blockers
    with pytest.raises(PlanRenderabilityError):
        _repair_renderer_segments(segments, (issue,), "Hello?!")
    assert segments == [punctuation]


def test_language_change_blocks_merge_but_allows_safe_neutral_drop() -> None:
    french = _segment("seg-fr", "bonjour", 0, 7, language="fr-FR")
    punctuation = _segment("seg-punc", ".", 7, 8, language="en-US")
    segments = [french, punctuation]
    issue = _assess(segments, _punctuation_issue(punctuation), "bonjour.")

    assert issue.repair_assessment is not None
    assert issue.repair_assessment.safe is True
    assert issue.repair_assessment.action == "drop"
    assert "language changes from en-US to fr-FR" in issue.repair_assessment.blockers
    repaired, repairs = _repair_renderer_segments(segments, (issue,), "bonjour.")
    assert [segment.text for segment in repaired] == ["bonjour"]
    assert repairs[0].repair == "drop_non_speech_punctuation"


def test_audio_instruction_at_join_prevents_merge_and_drop() -> None:
    lexical = _segment("seg-000000", "Hello", 0, 5)
    punctuation = _segment("seg-000001", ".", 5, 6)
    audio = AnnotationSpan(
        id="annotation-audio",
        kind="audio",
        attrs={"tag": "audio", "src": "clip.wav"},
        structural_start=5,
        structural_end=5,
        spoken_start=5,
        spoken_end=5,
    )
    segments = [lexical, punctuation]
    issue = _assess(
        segments,
        _punctuation_issue(punctuation),
        "Hello.",
        annotations=(audio,),
    )

    assert issue.repair_assessment is not None
    assert issue.repair_assessment.safe is False
    assert any("audio" in blocker for blocker in issue.repair_assessment.blockers)
    with pytest.raises(PlanRenderabilityError) as error:
        _repair_renderer_segments(segments, (issue,), "Hello.")
    assert error.value.mode == "repair"
    assert error.value.issues[0].code == "renderability.repair_failed"
    assert "audio" in str(error.value)


def test_semantic_directives_and_boundaries_block_punctuation_removal() -> None:
    lexical = _segment("seg-000000", "Hello", 0, 5)
    punctuation = replace(
        _segment("seg-000001", "?!", 5, 7),
        directives=SegmentDirectives(emphasis=EmphasisDirective(level="strong")),
    )
    segments = [lexical, punctuation]
    issue = _assess(segments, _punctuation_issue(punctuation), "Hello?!")

    assert issue.repair_assessment is not None
    assert issue.repair_assessment.safe is False
    assert any("emphasis directive" in blocker for blocker in issue.repair_assessment.blockers)

    plain_punctuation = _segment("seg-000002", "?!", 5, 7)
    isolated = [plain_punctuation]
    issue = _assess(
        isolated,
        _punctuation_issue(plain_punctuation, index=0),
        "Hello?!",
        semantic_boundaries=(SemanticBoundary("semantic-0", 6, "clause"),),
    )
    assert issue.repair_assessment is not None
    assert issue.repair_assessment.safe is False
    assert "clause semantic boundary at spoken position 6" in issue.repair_assessment.blockers


@pytest.mark.parametrize(
    ("tag", "attrs"),
    (
        ("pronunciation", {"tag": "pronunciation", "ph": "dʒɪf"}),
        ("sub", {"tag": "sub", "sub": "spoken words"}),
        ("say-as", {"tag": "say-as", "as": "characters"}),
    ),
)
def test_semantic_annotations_on_punctuation_block_merge_and_removal(
    tag: str, attrs: dict[str, str]
) -> None:
    lexical = _segment("seg-000000", "Hello", 0, 5)
    punctuation = replace(
        _segment("seg-000001", "?!", 5, 7),
        annotation_ids=("annotation-semantic",),
    )
    annotation = AnnotationSpan(
        id="annotation-semantic",
        kind=tag,
        attrs=attrs,
        structural_start=5,
        structural_end=7,
        spoken_start=5,
        spoken_end=7,
    )
    segments = [lexical, punctuation]
    issue = _assess(
        segments,
        _punctuation_issue(punctuation),
        "Hello?!",
        annotations=(annotation,),
    )

    assert issue.repair_assessment is not None
    assert issue.repair_assessment.safe is False
    assert (
        f"{tag} annotation belongs to the punctuation segment" in issue.repair_assessment.blockers
    )


def test_symbol_only_content_fails_without_a_guessed_repair() -> None:
    for mode in ("strict", "repair"):
        config = PlannerConfig(
            language="en-US",
            text_preparation="identity",
            renderability_mode=mode,
        )
        with pytest.raises(PlanRenderabilityError) as error:
            UtterancePlanner(config).plan("€")
        issue = error.value.issues[0]
        assert issue.code == "renderability.symbol_only"
        assert issue.repair_assessment is not None
        assert issue.repair_assessment.safe is False
        assert "will not guess" in str(error.value)
        assert error.value.mode == mode


def test_strict_attempt_retains_blocked_candidate_and_compile_still_raises() -> None:
    source = "Hello.\n\n.\n\nWorld."
    config = PlannerConfig(
        language="en-US",
        text_preparation="identity",
        renderability_mode="strict",
    )
    planner = UtterancePlanner(config)

    attempt = planner.compile_attempt(source)
    functional = compile_attempt(source, input_format="plain", config=config)
    assert functional.status == "blocked"

    assert attempt.status == "blocked"
    assert not attempt.ok
    assert attempt.renderability.issues
    issue = attempt.renderability.issues[0]
    segment = next(item for item in attempt.candidate.segments if item.id == issue.segment_id)
    assert segment.text == issue.text == "."
    assert issue.source_start is not None
    assert issue.source_end is not None
    assert source[issue.source_start : issue.source_end] == issue.text
    assert attempt.candidate.plan_id == ""
    with pytest.raises(ValueError, match="blocked planning-attempt draft"):
        attempt.candidate.to_plan()

    with pytest.raises(PlanRenderabilityError) as error:
        planner.compile(source)
    assert error.value.mode == "strict"
    assert error.value.issues == attempt.renderability.issues


def test_safe_repair_attempt_returns_a_canonical_plan() -> None:
    config = PlannerConfig(language="en-US", text_preparation="identity")
    attempt = UtterancePlanner(config).compile_attempt("Hello.\n\n.\n\nWorld.")

    assert attempt.status == "repaired"
    assert attempt.ok
    assert len(attempt.repairs) == 1
    assert attempt.repairs[0].repair_assessment is not None
    assert attempt.repairs[0].repair_assessment.safe
    plan = attempt.candidate.to_plan()
    plan.validate()
    assert [segment.text for segment in plan.segments] == ["Hello.", "World."]


def test_unsafe_repair_attempt_is_blocked_and_draft_structure_is_checked() -> None:
    from utterplan.exceptions import PlanValidationError
    from utterplan.model import validate_plan_structure

    config = PlannerConfig(
        language="en-US",
        text_preparation="identity",
        renderability_mode="repair",
    )
    attempt = UtterancePlanner(config).compile_attempt("€")

    assert attempt.status == "blocked"
    assert attempt.renderability.issues[0].repair_assessment is not None
    assert not attempt.renderability.issues[0].repair_assessment.safe
    with pytest.raises(ValueError, match="blocked planning-attempt draft"):
        attempt.candidate.to_plan()

    malformed = replace(
        attempt.candidate._plan,
        segments=(replace(attempt.candidate.segments[0], spoken_end=100),),
    )
    with pytest.raises(PlanValidationError, match="segment range"):
        validate_plan_structure(malformed)


@pytest.mark.parametrize(
    ("source", "mode", "expected_status"),
    [
        ("Ready.", "strict", "renderable"),
        ("Hello.\n\n.\n\nWorld.", "repair", "repaired"),
        ("€", "strict", "blocked"),
    ],
)
def test_planning_attempt_toml_roundtrips_all_outcomes_and_stays_noncanonical(
    source: str, mode: str, expected_status: str
) -> None:
    config = PlannerConfig(
        language="en-US",
        text_preparation="identity",
        renderability_mode=mode,
    )
    attempt = UtterancePlanner(config).compile_attempt(source)
    repeated = UtterancePlanner(config).compile_attempt(source)
    serialized = attempt.to_toml()
    restored = type(attempt).from_toml(serialized)

    assert attempt.status == expected_status
    assert repeated.attempt_id == attempt.attempt_id
    assert restored == attempt
    assert restored.to_toml() == serialized
    assert restored.to_dict() == attempt.to_dict()
    assert 'schema = "utterplan.planning-attempt.v1"' in serialized
    with pytest.raises(PlanFormatError):
        UtterancePlan.from_toml(serialized)
    with pytest.raises(PlanFormatError):
        UtterancePlan.from_dict(attempt.to_dict())
