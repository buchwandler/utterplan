from __future__ import annotations

from dataclasses import replace

import pytest
from renderplan import (
    PauseItem,
    PausePolicy,
    PlanningPolicy,
    PreflightCheck,
    PreflightReport,
    RenderPlan,
    RenderProfile,
    ReplanRequest,
    RoleProfile,
    SourceSpan,
    SpeechItem,
)

from utterplan import (
    FlowPlan,
    FlowSegment,
    FlowUnit,
    PronunciationDirective,
    ReplacementView,
    SegmentDirectives,
    TokenView,
)
from utterplan.renderplan_export import build_render_plan
from utterplan.renderplan_grouping import group_initial_plan
from utterplan.renderplan_projection import (
    RenderPlanProjectionError,
    SourceSegmentIndex,
    build_source_index,
)
from utterplan.renderplan_replan import replan_flow


def _profile(*, fallback: tuple[str, ...] = ("clause", "token")) -> RenderProfile:
    return RenderProfile(
        roles={"narrator": RoleProfile(language="en-US", binding={"engine": "fixture"})},
        default_role="narrator",
        planning=PlanningPolicy(split="sentence", capacity_fallback=fallback),
        pauses=PausePolicy(mode="manual", durations_ms={"sentence": 500, "clause": 180}),
    )


def _plan(*segments: FlowSegment) -> FlowPlan:
    return FlowPlan(language="en-US", flow=(FlowUnit(tuple(segments)),))


def _build_previous(
    plan: FlowPlan, profile: RenderProfile
) -> tuple[SourceSegmentIndex, RenderProfile, RenderPlan]:
    index = build_source_index(plan)
    previous = RenderPlan(
        source_plan_id=index.source_plan_id,
        render_profile_id=profile.profile_id or profile.computed_id(),
        flow=group_initial_plan(index, profile),
    ).with_identity()
    return index, profile, previous


def _preflight(
    previous: RenderPlan,
    profile: RenderProfile,
    failed: tuple[SpeechItem, ...],
    *,
    metric: str = "model_tokens",
    measured: int = 512,
    maximum: int = 510,
) -> PreflightReport:
    checks = tuple(
        PreflightCheck(
            segment_number=speech.number,
            segment_id=speech.segment_id or speech.computed_id(),
            status="too_long",
            metric=metric,
            measured=measured,
            maximum=maximum,
            source="fixture-renderer",
        )
        for speech in failed
    )
    requests = tuple(
        ReplanRequest(
            segment_number=speech.number,
            segment_id=speech.segment_id or speech.computed_id(),
            source=speech.source,
            current_level=speech.planning_level,
            metric=metric,
            measured=measured,
            maximum=maximum,
        )
        for speech in failed
    )
    return PreflightReport(
        render_plan_id=previous.plan_id or previous.computed_id(),
        source_plan_id=previous.source_plan_id,
        render_profile_id=profile.profile_id or profile.computed_id(),
        status="replan",
        checks=checks,
        replan=requests,
    ).with_identity()


def _speech_text(flow: tuple[object, ...] | list[object]) -> list[SpeechItem]:
    return [item for item in flow if isinstance(item, SpeechItem)]


def test_public_replan_loop_preserves_unchanged_requests_and_refines_only_failed_source() -> None:
    text = "one two three four"
    plan = _plan(
        FlowSegment(
            text,
            "en-US",
            tokens=(TokenView(0, 3), TokenView(4, 7), TokenView(8, 13), TokenView(14, 18)),
            boundary_after=("sentence",),
        ),
        FlowSegment("Unchanged later.", "en-US", boundary_after=("sentence",)),
    )
    profile = _profile()
    previous = build_render_plan(plan, profile)
    failed = previous.speech[0]
    unchanged = previous.speech[-1]
    report = _preflight(previous, profile, (failed,))

    replanned = build_render_plan(plan, profile, previous_plan=previous, preflight=report)
    replanned.validate_against_profile(profile)
    children = [
        speech
        for speech in replanned.speech
        if speech.source
        and all(
            span.locator == failed.source[0].locator
            and failed.source[0].start <= span.start < span.end <= failed.source[0].end
            for span in speech.source
        )
    ]

    assert replanned.plan_id != previous.plan_id
    assert replanned.speech[-1].text == unchanged.text
    assert replanned.speech[-1].segment_id == unchanged.segment_id
    assert len(children) == 2
    assert "".join(speech.text for speech in children) == failed.text
    assert all(len(speech.text) < len(failed.text) for speech in children)
    assert all(speech.segment_id != failed.segment_id for speech in children)


def test_replan_replaces_only_failed_occurrence_and_preserves_later_id() -> None:
    plan = _plan(
        FlowSegment("One ", "en-US", boundary_after=("clause",)),
        FlowSegment("two ", "en-US", boundary_after=("clause",)),
        FlowSegment("three.", "en-US", boundary_after=("sentence",)),
        FlowSegment("Later.", "en-US", boundary_after=("sentence",)),
    )
    index, profile, previous = _build_previous(plan, _profile())
    old_speech = previous.speech
    failed = old_speech[0]
    report = _preflight(previous, profile, (failed,))

    flow = replan_flow(index, profile, previous, report)
    speech = _speech_text(flow)

    assert [item.text for item in speech] == ["One ", "two ", "three.", "Later."]
    assert [item.number for item in speech] == [1, 2, 3, 4]
    assert [item.planning_level for item in speech] == ["clause", "clause", "clause", "sentence"]
    assert [item.split_reason for item in speech[:3]] == ["capacity", "capacity", "capacity"]
    assert [item.semantic_end for item in speech[:3]] == ["clause", "clause", "sentence"]
    assert speech[-1].segment_id == old_speech[-1].segment_id
    assert "".join(item.text for item in speech[:3]) == failed.text
    assert [item.reason for item in flow if isinstance(item, PauseItem)] == [
        "capacity",
        "capacity",
        "sentence",
        "sentence",
    ]
    rebuilt = RenderPlan(
        source_plan_id=previous.source_plan_id,
        render_profile_id=previous.render_profile_id,
        flow=flow,
    ).with_identity()
    assert rebuilt.plan_id != previous.plan_id


def test_replan_preserves_parenthetical_semantic_end_on_last_clause_child() -> None:
    plan = _plan(
        FlowSegment("A ", "en-US", boundary_after=("clause",)),
        FlowSegment("B ", "en-US", boundary_after=("parenthetical",)),
        FlowSegment(
            "(x)",
            "en-US",
            boundary_before=("parenthetical",),
            boundary_after=("sentence",),
        ),
    )
    profile = replace(
        _profile(),
        pauses=PausePolicy(
            mode="manual",
            durations_ms={"clause": 180, "parenthetical": 180, "sentence": 500},
        ),
        profile_id=None,
    )
    index, profile, previous = _build_previous(plan, profile)
    failed = previous.speech[0]
    assert failed.text == "A B "
    assert failed.semantic_end == "parenthetical"

    flow = replan_flow(index, profile, previous, _preflight(previous, profile, (failed,)))
    speech = _speech_text(flow)

    assert [item.text for item in speech] == ["A ", "B ", "(x)"]
    assert [item.semantic_end for item in speech] == ["clause", "parenthetical", "sentence"]
    assert [item.reason for item in flow if isinstance(item, PauseItem)] == [
        "capacity",
        "parenthetical",
        "sentence",
    ]


def test_successful_prior_splits_survive_replanning_an_unrelated_child() -> None:
    plan = _plan(
        FlowSegment("A1 ", "en-US", boundary_after=("clause",)),
        FlowSegment("A2. ", "en-US", boundary_after=("sentence",)),
        FlowSegment(
            "Later request.",
            "en-US",
            tokens=(TokenView(0, 5), TokenView(6, 13)),
            boundary_after=("sentence",),
        ),
    )
    index = build_source_index(plan)
    profile = _profile(fallback=("token",))
    later_source = (SourceSpan("f000000.s002", 0, len("Later request.")),)
    earlier_source_one = (SourceSpan("f000000.s000", 0, 3),)
    earlier_source_two = (SourceSpan("f000000.s001", 0, 4),)
    narrator = profile.roles["narrator"]
    earlier_one = SpeechItem(
        number=1,
        text=index.text_for(earlier_source_one),
        language="en-US",
        role="narrator",
        binding=dict(narrator.binding),
        source=earlier_source_one,
        planning_level="clause",
        split_reason="capacity",
        semantic_end="clause",
    ).with_identity()
    earlier_two = SpeechItem(
        number=2,
        text=index.text_for(earlier_source_two),
        language="en-US",
        role="narrator",
        binding=dict(narrator.binding),
        source=earlier_source_two,
        planning_level="clause",
        split_reason="capacity",
        semantic_end="sentence",
    ).with_identity()
    later = SpeechItem(
        number=3,
        text=index.text_for(later_source),
        language="en-US",
        role="narrator",
        binding=dict(narrator.binding),
        source=later_source,
        planning_level="sentence",
        split_reason="policy",
        semantic_end="sentence",
    ).with_identity()
    previous = RenderPlan(
        source_plan_id=index.source_plan_id,
        render_profile_id=profile.computed_id(),
        flow=(earlier_one, earlier_two, PauseItem(500, "sentence").with_identity(), later),
    ).with_identity()
    report = _preflight(previous, profile, (later,))

    flow = replan_flow(index, profile, previous, report)
    speech = _speech_text(flow)

    assert [item.text for item in speech[:2]] == ["A1 ", "A2. "]
    assert [item.segment_id for item in speech[:2]] == [
        earlier_one.segment_id,
        earlier_two.segment_id,
    ]
    assert speech[2].text == "Later"
    assert speech[2].segment_id != later.segment_id


def test_token_fallback_never_splits_lexical_tokens_and_repeats_deterministically() -> None:
    text = "one two three four"
    plan = _plan(
        FlowSegment(
            text,
            "en-US",
            tokens=(TokenView(0, 3), TokenView(4, 7), TokenView(8, 13), TokenView(14, 18)),
            boundary_after=("sentence",),
        )
    )
    index, profile, previous = _build_previous(plan, _profile(fallback=("token",)))
    report = _preflight(previous, profile, (previous.speech[0],))

    first = replan_flow(index, profile, previous, report)
    again = replan_flow(index, profile, previous, report)
    first_speech = _speech_text(first)

    assert first == again
    assert "".join(item.text for item in first_speech) == text
    assert len(first_speech) == 2
    assert all(item.planning_level == "token" for item in first_speech)
    for speech in first_speech:
        bundle = index.tokens_for(speech.source)
        assert bundle is not None
        assert all(
            speech.text[start:end] in {"one", "two", "three", "four"} for start, end in bundle.span
        )


def test_repeated_token_bisection_converges_without_rebuilding_prior_partition() -> None:
    words = tuple("abcdefgh")
    text = " ".join(words)
    tokens = tuple(TokenView(position * 2, position * 2 + 1) for position, _ in enumerate(words))
    plan = _plan(FlowSegment(text, "en-US", tokens=tokens, boundary_after=("sentence",)))
    index, profile, initial = _build_previous(plan, _profile(fallback=("token",)))
    initial_report = _preflight(initial, profile, (initial.speech[0],), measured=999, maximum=2)
    expected_first = replan_flow(index, profile, initial, initial_report)

    previous = initial
    for _ in range(3):
        failing = []
        for speech in previous.speech:
            bundle = index.tokens_for(speech.source)
            assert bundle is not None
            if len(bundle.span) > 2:
                failing.append(speech)
        if not failing:
            break
        report = _preflight(previous, profile, tuple(failing), measured=999, maximum=2)
        flow = replan_flow(index, profile, previous, report)
        previous = RenderPlan(
            source_plan_id=previous.source_plan_id,
            render_profile_id=previous.render_profile_id,
            flow=flow,
        ).with_identity()

    assert expected_first == replan_flow(index, profile, initial, initial_report)
    assert all(
        (bundle := index.tokens_for(item.source)) is not None and len(bundle.span) <= 2
        for item in previous.speech
    )
    assert "".join(item.text for item in previous.speech) == text
    assert previous.plan_id != initial.plan_id


def test_replacement_and_atomic_pronunciation_ranges_are_protected() -> None:
    text = "one two three"
    plan = _plan(
        FlowSegment(
            text,
            "en-US",
            tokens=(TokenView(0, 3), TokenView(4, 7), TokenView(8, 13)),
            replacements=(ReplacementView(0, len(text), "source phrase", kind="ssmd-sub"),),
            boundary_after=("sentence",),
        )
    )
    index, profile, previous = _build_previous(plan, _profile(fallback=("token",)))
    request_plan = _preflight(previous, profile, (previous.speech[0],))

    with pytest.raises(RenderPlanProjectionError) as error:
        replan_flow(index, profile, previous, request_plan)
    assert error.value.code == "renderplan.capacity.unsplittable"
    assert previous.speech[0].segment_id in str(error.value)
    assert "f000000.s000[0:13]" in str(error.value)
    assert "current_level=sentence" in str(error.value)
    assert "model_tokens" in str(error.value)
    assert "512" in str(error.value) and "510" in str(error.value)

    pronunciation = _plan(
        FlowSegment(
            text,
            "en-US",
            tokens=(TokenView(0, 3), TokenView(4, 7), TokenView(8, 13)),
            directives=SegmentDirectives(pronunciation=PronunciationDirective("fəˈnɛtɪk")),
            boundary_after=("sentence",),
        )
    )
    pronunciation_index, pronunciation_profile, pronunciation_previous = _build_previous(
        pronunciation, _profile(fallback=("token",))
    )
    with pytest.raises(RenderPlanProjectionError) as pronunciation_error:
        replan_flow(
            pronunciation_index,
            pronunciation_profile,
            pronunciation_previous,
            _preflight(
                pronunciation_previous, pronunciation_profile, (pronunciation_previous.speech[0],)
            ),
        )
    assert pronunciation_error.value.code == "renderplan.capacity.unsplittable"


def test_stale_preflight_wrong_previous_and_stale_source_are_rejected() -> None:
    plan = _plan(
        FlowSegment(
            "one two three",
            "en-US",
            tokens=(TokenView(0, 3), TokenView(4, 7), TokenView(8, 13)),
            boundary_after=("sentence",),
        )
    )
    index, profile, previous = _build_previous(plan, _profile(fallback=("token",)))
    report = _preflight(previous, profile, (previous.speech[0],))

    changed_flow = (*previous.flow, PauseItem(1, "changed").with_identity())
    other_previous = replace(previous, flow=changed_flow, plan_id=None).with_identity()
    with pytest.raises(RenderPlanProjectionError) as stale_report:
        replan_flow(index, profile, other_previous, report)
    assert stale_report.value.code == "renderplan.replan.preflight"

    other_source = _plan(FlowSegment("different.", "en-US", boundary_after=("sentence",)))
    _, other_profile, foreign_previous = _build_previous(other_source, profile)
    foreign_report = _preflight(foreign_previous, other_profile, (foreign_previous.speech[0],))
    with pytest.raises(RenderPlanProjectionError) as wrong_source:
        replan_flow(index, profile, foreign_previous, foreign_report)
    assert wrong_source.value.code == "renderplan.replan.source_plan_id"

    speech = previous.speech[0]
    stale_speech = replace(speech, text="not the source text", segment_id=None).with_identity()
    stale_previous = RenderPlan(
        source_plan_id=previous.source_plan_id,
        render_profile_id=previous.render_profile_id,
        flow=(stale_speech, *previous.flow[1:]),
    ).with_identity()
    stale_request = _preflight(stale_previous, profile, (stale_previous.speech[0],))
    with pytest.raises(RenderPlanProjectionError) as stale_source:
        replan_flow(index, profile, stale_previous, stale_request)
    assert stale_source.value.code == "renderplan.replan.source_stale"
