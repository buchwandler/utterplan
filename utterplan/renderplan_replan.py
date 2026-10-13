"""Validated deterministic refinement of prior RenderPlan speech partitions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import TypeAlias

from renderplan import (
    AudioItem,
    PauseItem,
    PreflightReport,
    RenderPlan,
    RenderProfile,
    ReplanRequest,
    SourceSpan,
    SpeechItem,
)

from .renderplan_grouping import (
    _capacity_pause_at_offset,
    _child_speech,
    _clause_chunks,
    _legal_token_cuts,
    _semantic_end_at_source_end,
    _split_source,
    _token_count_before,
)
from .renderplan_projection import RenderPlanProjectionError, SourceSegmentIndex

FlowItem: TypeAlias = AudioItem | PauseItem | SpeechItem


def replan_flow(
    index: SourceSegmentIndex,
    profile: RenderProfile,
    previous: RenderPlan,
    preflight: PreflightReport,
) -> tuple[FlowItem, ...]:
    """Replace only failed prior speech occurrences and preserve all other flow items."""
    _validate_replan_inputs(index, profile, previous, preflight)
    occurrences = {
        (speech.number, speech.segment_id or speech.computed_id()): speech
        for speech in previous.speech
    }
    replacements: dict[tuple[int, str], tuple[FlowItem, ...]] = {}
    for request in preflight.replan:
        key = (request.segment_number, request.segment_id)
        speech = occurrences[key]
        replacements[key] = _split_failed_speech(index, profile, speech, request)

    flow: list[FlowItem] = []
    for item in previous.flow:
        if not isinstance(item, SpeechItem):
            flow.append(item)
            continue
        key = (item.number, item.segment_id or item.computed_id())
        flow.extend(replacements.get(key, (item,)))
    return _renumber_and_identify(flow)


def _validate_replan_inputs(
    index: SourceSegmentIndex,
    profile: RenderProfile,
    previous: RenderPlan,
    preflight: PreflightReport,
) -> None:
    if not isinstance(profile, RenderProfile):
        raise RenderPlanProjectionError(
            "replanning requires a RenderProfile",
            code="renderplan.replan.profile_type",
        )
    expected_profile_id = profile.profile_id or profile.computed_id()

    if not isinstance(previous, RenderPlan):
        raise RenderPlanProjectionError(
            "replanning requires the previous RenderPlan",
            code="renderplan.replan.previous_type",
        )
    expected_previous_id = previous.computed_id()
    if previous.plan_id is not None and previous.plan_id != expected_previous_id:
        raise RenderPlanProjectionError(
            "previous RenderPlan identity does not match its content",
            code="renderplan.replan.previous_identity",
        )
    if previous.source_plan_id != index.source_plan_id:
        raise RenderPlanProjectionError(
            "previous RenderPlan source_plan_id does not match current UtterPlan",
            code="renderplan.replan.source_plan_id",
        )
    if previous.render_profile_id != expected_profile_id:
        raise RenderPlanProjectionError(
            "previous RenderPlan render_profile_id does not match current RenderProfile",
            code="renderplan.replan.profile_id",
        )
    try:
        previous.validate_against_profile(profile)
    except ValueError as exc:
        raise RenderPlanProjectionError(
            f"previous RenderPlan is invalid for the RenderProfile: {exc}",
            code="renderplan.replan.previous_profile",
        ) from exc
    if not isinstance(preflight, PreflightReport):
        raise RenderPlanProjectionError(
            "replanning requires the matching PreflightReport",
            code="renderplan.replan.preflight_type",
        )
    try:
        preflight.validate_against(previous)
    except ValueError as exc:
        raise RenderPlanProjectionError(
            f"PreflightReport does not validate against previous RenderPlan: {exc}",
            code="renderplan.replan.preflight",
        ) from exc
    if preflight.status != "replan":
        raise RenderPlanProjectionError(
            f"PreflightReport status must be 'replan', received {preflight.status!r}",
            code="renderplan.replan.preflight_status",
        )

    for speech in previous.speech:
        try:
            current_text = index.text_for(speech.source)
        except RenderPlanProjectionError as exc:
            raise RenderPlanProjectionError(
                f"previous speech {speech.number} source no longer resolves: {exc}",
                code="renderplan.replan.source_stale",
            ) from exc
        if current_text != speech.text:
            raise RenderPlanProjectionError(
                f"previous speech {speech.number} source text no longer matches its exact request text",
                code="renderplan.replan.source_stale",
            )


def _split_failed_speech(
    index: SourceSegmentIndex,
    profile: RenderProfile,
    speech: SpeechItem,
    request: ReplanRequest,
) -> tuple[FlowItem, ...]:
    if request.source != speech.source:
        raise RenderPlanProjectionError(
            f"failed speech {speech.number} source coverage does not match its previous occurrence",
            code="renderplan.replan.source_coverage",
        )
    current_text = index.text_for(request.source)
    if current_text != speech.text:
        raise RenderPlanProjectionError(
            f"failed speech {speech.number} source text does not equal the previous request text",
            code="renderplan.replan.source_stale",
        )

    configured = profile.planning.capacity_fallback
    if speech.planning_level in {"sentence", "paragraph", "hard"}:
        fallbacks = tuple(level for level in configured if level in {"clause", "token"})
    else:
        fallbacks = tuple(level for level in configured if level == "token")

    for fallback in fallbacks:
        if fallback == "clause":
            chunks = _clause_chunks(index, speech)
            if len(chunks) > 1:
                return _clause_children(index, profile, speech, chunks)
        elif fallback == "token":
            split = _token_bisect(index, profile, speech)
            if split is not None:
                left, right, offset = split
                return (
                    left,
                    _capacity_pause_at_offset(index, speech.source, offset, profile),
                    right,
                )
    raise _unsplittable(speech, request)


def _clause_children(
    index: SourceSegmentIndex,
    profile: RenderProfile,
    speech: SpeechItem,
    chunks: Sequence[Sequence[SourceSpan]],
) -> tuple[FlowItem, ...]:
    result: list[FlowItem] = []
    cumulative = 0
    for position, source in enumerate(chunks):
        semantic_end = (
            speech.semantic_end
            if position == len(chunks) - 1
            else _semantic_end_at_source_end(index, source)
        )
        result.append(
            _child_speech(
                speech,
                index,
                source,
                profile,
                planning_level="clause",
                split_reason="capacity",
                semantic_end=semantic_end,
            )
        )
        cumulative += sum(end - start for _, start, end in index.ordered_slices(source))
        if position < len(chunks) - 1:
            result.append(_capacity_pause_at_offset(index, speech.source, cumulative, profile))
    return tuple(result)


def _token_bisect(
    index: SourceSegmentIndex, profile: RenderProfile, speech: SpeechItem
) -> tuple[SpeechItem, SpeechItem, int] | None:
    legal_cuts = _legal_token_cuts(index, speech.source)
    if not legal_cuts:
        return None
    tokens = index.tokens_for(speech.source)
    token_count = len(tokens.span) if tokens is not None else 0
    if token_count < 2:
        return None
    cut = min(
        legal_cuts,
        key=lambda candidate: (
            abs(_token_count_before(index, speech.source, candidate) * 2 - token_count),
            candidate,
        ),
    )
    left_source, right_source = _split_source(index, speech.source, cut)
    if not left_source or not right_source:
        return None
    left = _child_speech(
        speech,
        index,
        left_source,
        profile,
        planning_level="token",
        split_reason="capacity",
        semantic_end=_semantic_end_at_source_end(index, left_source),
    )
    right = _child_speech(
        speech,
        index,
        right_source,
        profile,
        planning_level="token",
        split_reason="capacity",
        semantic_end=speech.semantic_end,
    )
    return left, right, cut


def _unsplittable(speech: SpeechItem, request: ReplanRequest) -> RenderPlanProjectionError:
    source = ", ".join(f"{span.locator}[{span.start}:{span.end}]" for span in request.source)
    return RenderPlanProjectionError(
        f"capacity split is unsplittable for speech {request.segment_number} "
        f"({request.segment_id}), source={source}, current_level={request.current_level}, "
        f"diagnostic metric={request.metric}, measured={request.measured}, maximum={request.maximum}",
        code="renderplan.capacity.unsplittable",
    )


def _renumber_and_identify(items: Sequence[FlowItem]) -> tuple[FlowItem, ...]:
    result: list[FlowItem] = []
    number = 0
    for item in items:
        if isinstance(item, SpeechItem):
            number += 1
            result.append(replace(item, number=number, segment_id=None).with_identity())
        elif isinstance(item, PauseItem):
            result.append(replace(item, pause_id=None).with_identity())
        elif isinstance(item, AudioItem):
            result.append(replace(item, audio_id=None).with_identity())
    return tuple(result)


__all__ = ["replan_flow"]
