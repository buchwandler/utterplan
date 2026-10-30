"""Deterministic initial grouping from schema-v7 UtterPlan flow topology."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import replace
from typing import Any, TypeAlias

from renderplan import (
    AudioItem,
    PauseItem,
    RenderProfile,
    RoleProfile,
    SourceSpan,
    SpeechItem,
)

from .model import FlowSegment, PauseIntent
from .renderplan_pause_timing import (
    PauseTimingConfig,
    PauseTimingContext,
    resolve_automatic_pause_duration,
)
from .renderplan_projection import RenderPlanProjectionError, SourceSegmentIndex, SourceSegmentRef

FlowItem: TypeAlias = AudioItem | PauseItem | SpeechItem

_TIMED_PAUSE = re.compile(r"^(0|[1-9][0-9]*)ms$")
_STRUCTURAL_BOUNDARY_PRIORITY = {"clause": 1, "sentence": 2, "paragraph": 3, "voice_change": 4}
_ADAPTIVE_BOUNDARIES = frozenset({"clause", "sentence", "paragraph"})
_AUTHORED_PAUSES = frozenset({"timed", "x-weak", "weak", "medium", "strong", "x-strong"})


def group_initial_plan(
    index: SourceSegmentIndex,
    profile: RenderProfile,
    *,
    pause_timing: PauseTimingConfig | None = None,
) -> tuple[FlowItem, ...]:
    """Build ordered speech/audio/pause operations using only v7 source semantics."""
    pause_timing = pause_timing or PauseTimingConfig()
    flow: list[FlowItem] = []
    group_source: list[SourceSpan] = []
    group_state: tuple[str, str, str, RoleProfile] | None = None
    refs = index.ordered_refs

    def close_group(
        *,
        planning_level: str | None = None,
        split_reason: str = "policy",
        semantic_end: str = "none",
    ) -> None:
        nonlocal group_source, group_state
        if not group_source or group_state is None:
            group_source = []
            group_state = None
            return
        role, role_language, _source_language, role_profile = group_state
        source = tuple(group_source)
        flow.append(
            SpeechItem(
                number=1 + sum(isinstance(item, SpeechItem) for item in flow),
                text=index.text_for(source),
                language=role_language,
                role=role,
                binding=dict(role_profile.binding),
                source=source,
                planning_level=planning_level or profile.planning.split,
                split_reason=split_reason,
                semantic_end=semantic_end,
                tokens=index.tokens_for(
                    source, required_fields=role_profile.requirements.token_fields
                ),
                controls=index.controls_for(source),
            )
        )
        group_source = []
        group_state = None

    for position, ref in enumerate(refs):
        segment = ref.segment
        audio = segment.directives.audio
        state = (
            None
            if audio is not None or not segment.text
            else _effective_state(segment, ref, profile)
        )
        boundary = "none"
        if position == 0:
            leading = _resolve_pause(
                _pause_intent(segment.pause_before, ref.locator),
                None,
                semantic_end=None,
                profile=profile,
                capacity_cut=False,
            )
            if leading is not None:
                flow.append(leading)
        else:
            left_ref = refs[position - 1]
            left = left_ref.segment
            edge_kinds = _boundary_kinds(left, segment)
            boundary = _structural_boundary_kind(edge_kinds)
            left_pause = _pause_intent(left.pause_after, left_ref.locator)
            right_pause = _pause_intent(segment.pause_before, ref.locator)
            media_change = (left.directives.audio is None) != (audio is None)
            role_change = bool(group_state and state and group_state[0] != state[0])
            language_change = bool(
                group_state and state and (group_state[1] != state[1] or group_state[2] != state[2])
            )
            voice_change = role_change or boundary == "voice_change"
            policy_split = _policy_splits(profile.planning.split, boundary)
            hard_reason = (
                "voice_change"
                if voice_change
                else "directive_change"
                if language_change
                else "media"
                if media_change
                else None
            )
            authored_break = _has_timed_or_named(left_pause) or _has_timed_or_named(right_pause)
            authored_none_only = not authored_break and any(
                intent is not None and intent.type == "none" for intent in (left_pause, right_pause)
            )
            parenthetical_policy_break = (
                "parenthetical" in edge_kinds
                and _parenthetical_pause_enabled(profile)
                and not authored_none_only
            )
            should_close = (
                policy_split
                or hard_reason is not None
                or authored_break
                or parenthetical_policy_break
            )
            if should_close:
                if voice_change:
                    semantic_boundary = "voice_change"
                elif policy_split:
                    semantic_boundary = boundary
                elif parenthetical_policy_break:
                    semantic_boundary = "parenthetical"
                else:
                    semantic_boundary = None
                pause_context = (
                    _build_pause_context(index, semantic_boundary, tuple(group_source), ref)
                    if group_source and semantic_boundary in _ADAPTIVE_BOUNDARIES
                    else None
                )
                if group_source:
                    close_group(
                        planning_level="hard" if hard_reason else profile.planning.split,
                        split_reason=hard_reason or "policy",
                        semantic_end=semantic_boundary or "none",
                    )
                pause = _resolve_pause(
                    left_pause,
                    right_pause,
                    semantic_end=semantic_boundary,
                    profile=profile,
                    context=pause_context,
                    pause_timing=pause_timing,
                    capacity_cut=False,
                )
                if pause is not None:
                    flow.append(pause)
        if audio is not None:
            if group_source:
                close_group(planning_level="hard", split_reason="media", semantic_end=boundary)
            flow.append(_audio_item(ref))
            continue
        if not segment.text:
            continue
        if state is None:
            raise AssertionError("speech state was not resolved")
        if group_state is not None and group_state[:3] != state[:3]:
            changed_role = group_state[0] != state[0]
            close_group(
                planning_level="hard",
                split_reason="voice_change" if changed_role else "directive_change",
                semantic_end="voice_change" if changed_role else boundary,
            )
        if group_state is None:
            group_state = state
        group_source.append(SourceSpan(ref.locator, 0, len(segment.text)))

    if refs:
        last = refs[-1]
        terminal_boundary = _terminal_boundary(last.segment)
        semantic_end = (
            terminal_boundary
            if _policy_splits(profile.planning.split, terminal_boundary)
            else "none"
        )
        pause_context = (
            _build_pause_context(index, semantic_end, tuple(group_source), None)
            if group_source and semantic_end in _ADAPTIVE_BOUNDARIES
            else None
        )
        if group_source:
            close_group(semantic_end=semantic_end)
        trailing = _resolve_pause(
            _pause_intent(last.segment.pause_after, last.locator),
            None,
            semantic_end=semantic_end if semantic_end != "none" else None,
            profile=profile,
            capacity_cut=False,
            context=pause_context,
            pause_timing=pause_timing,
        )
        if trailing is not None:
            flow.append(trailing)

    expanded: list[FlowItem] = []
    for item in flow:
        if isinstance(item, SpeechItem):
            expanded.extend(_apply_initial_capacity(item, index, profile))
        else:
            expanded.append(item)
    return _renumber_and_identify(expanded)


def _effective_state(
    segment: FlowSegment, ref: SourceSegmentRef, profile: RenderProfile
) -> tuple[str, str, str, RoleProfile]:
    voice = segment.directives.voice
    role_name = profile.default_role
    if voice is not None:
        unsupported = {
            name: value
            for name, value in voice.to_dict().items()
            if name != "reference" and value is not None
        }
        if unsupported:
            raise RenderPlanProjectionError(
                f"voice fields cannot be represented by logical role resolution: {sorted(unsupported)}",
                code="renderplan.voice.unsupported",
                locator=ref.locator,
            )
        if voice.reference:
            role_name = voice.reference
    try:
        role = profile.roles[role_name]
    except KeyError as exc:
        raise RenderPlanProjectionError(
            f"logical voice role {role_name!r} is not defined by the RenderProfile",
            code="renderplan.role.missing",
            locator=ref.locator,
        ) from exc
    return role_name, role.language, segment.language, role


def _boundary_kinds(left: FlowSegment, right: FlowSegment) -> frozenset[str]:
    return frozenset(left.boundary_after).union(right.boundary_before)


def _structural_boundary_kind(kinds: Iterable[str]) -> str:
    return max(
        (kind for kind in kinds if kind in _STRUCTURAL_BOUNDARY_PRIORITY),
        key=_STRUCTURAL_BOUNDARY_PRIORITY.__getitem__,
        default="none",
    )


def _boundary_kind(left: FlowSegment, right: FlowSegment) -> str:
    return _structural_boundary_kind(_boundary_kinds(left, right))


def _terminal_boundary(segment: FlowSegment) -> str:
    return _structural_boundary_kind(segment.boundary_after)


def _parenthetical_pause_enabled(profile: RenderProfile) -> bool:
    return profile.pauses.mode == "manual" and "parenthetical" in profile.pauses.durations_ms


def _policy_splits(policy: str, boundary: str) -> bool:
    if boundary == "voice_change":
        return True
    if policy == "paragraph":
        return boundary == "paragraph"
    if policy == "sentence":
        return boundary in {"sentence", "paragraph"}
    if policy == "clause":
        return boundary in {"clause", "sentence", "paragraph"}
    raise RenderPlanProjectionError(
        f"unsupported planning split policy {policy!r}", code="renderplan.planning.policy"
    )


def _pause_intent(value: object, locator: str) -> PauseIntent | None:
    if value is None:
        return None
    if not isinstance(value, PauseIntent):
        raise RenderPlanProjectionError(
            f"unsupported pause intent {value!r}",
            code="renderplan.pause.unsupported",
            locator=locator,
        )
    return value


def _has_timed_or_named(intent: PauseIntent | None) -> bool:
    return intent is not None and intent.type in _AUTHORED_PAUSES


def _build_pause_context(
    index: SourceSegmentIndex,
    boundary: str,
    left_source: Sequence[SourceSpan],
    right_ref: SourceSegmentRef | None,
) -> PauseTimingContext:
    """Capture the current speech group before close_group clears its source."""
    slices = index.ordered_slices(left_source)
    left_tokens = tuple(
        token
        for ref, start, end in slices
        for token in ref.segment.tokens
        if token.end > start and token.start < end
    )
    left_ref = slices[-1][0]
    return PauseTimingContext(
        boundary=boundary,
        language=right_ref.segment.language if right_ref is not None else left_ref.segment.language,
        left_text=index.text_for(left_source),
        right_text=right_ref.segment.text if right_ref is not None else "",
        left_tokens=left_tokens,
        right_tokens=right_ref.segment.tokens if right_ref is not None else (),
        left_heading=left_ref.segment.heading,
        right_heading=right_ref.segment.heading if right_ref is not None else None,
    )


def _resolve_pause(
    left: PauseIntent | None,
    right: PauseIntent | None,
    *,
    semantic_end: str | None,
    profile: RenderProfile,
    context: PauseTimingContext | None = None,
    pause_timing: PauseTimingConfig | None = None,
    capacity_cut: bool,
) -> PauseItem | None:
    """Merge two authored edge intents once, then resolve to numeric milliseconds."""
    timed: list[tuple[int, PauseIntent]] = []
    named: list[tuple[int, PauseIntent]] = []
    has_none = False
    for intent in (left, right):
        if intent is None:
            continue
        if intent.type == "timed":
            match = _TIMED_PAUSE.fullmatch(intent.time or "")
            if match is None:
                raise RenderPlanProjectionError(
                    f"timed pause {intent.time!r} must use integer milliseconds",
                    code="renderplan.pause.duration",
                )
            timed.append((int(match.group(1)), intent))
        elif intent.type == "none":
            has_none = True
        else:
            duration = profile.pauses.durations_ms.get(intent.type)
            if duration is None:
                if profile.pauses.mode == "none":
                    duration = 0
                else:
                    raise RenderPlanProjectionError(
                        f"RenderProfile does not map authored pause intent {intent.type!r}",
                        code="renderplan.pause.unmapped",
                    )
            named.append((duration, intent))

    if timed:
        duration, intent = max(timed, key=lambda item: item[0])
        return PauseItem(duration, intent.type)
    if named:
        duration, intent = max(named, key=lambda item: item[0])
        return PauseItem(duration, intent.type)
    if has_none:
        return PauseItem(0, "authored_none")
    if semantic_end is not None:
        base_ms = profile.pauses.durations_ms.get(semantic_end, 0)
        duration_ms = base_ms
        if semantic_end in _ADAPTIVE_BOUNDARIES and context is not None:
            duration_ms = resolve_automatic_pause_duration(
                base_ms, context, pause_timing or PauseTimingConfig()
            ).duration_ms
        return PauseItem(duration_ms, semantic_end)
    if capacity_cut:
        return PauseItem(0, "capacity")
    return None


def _audio_item(ref: SourceSegmentRef) -> AudioItem:
    audio = ref.segment.directives.audio
    if audio is None:
        raise AssertionError("audio directive was not present")
    if not ref.segment.text:
        raise RenderPlanProjectionError(
            "RenderPlan AudioItem requires a non-empty prepared-text SourceSpan, but this audio "
            "segment has no prepared text",
            code="renderplan.audio.source_span",
            locator=ref.locator,
        )
    additional_directives = set(ref.segment.directives.to_dict()).difference({"audio"})
    if additional_directives:
        raise RenderPlanProjectionError(
            f"audio segment also carries unsupported speech directives: {sorted(additional_directives)}",
            code="renderplan.audio.unsupported",
            locator=ref.locator,
        )
    unsupported = {
        key: value
        for key, value in (
            ("alt_text", audio.alt_text),
            ("description", audio.description),
            ("repeat_duration", audio.repeat_duration),
            ("repeat_count", audio.repeat_count),
        )
        if value is not None
    }
    if unsupported:
        raise RenderPlanProjectionError(
            f"audio directive fields have no portable AudioItem representation: {sorted(unsupported)}",
            code="renderplan.audio.unsupported",
            locator=ref.locator,
        )
    options: dict[str, Any] = {}
    for key, value in (
        ("clip_begin", audio.clip_begin),
        ("clip_end", audio.clip_end),
        ("speed", audio.speed),
        ("sound_level", audio.sound_level),
    ):
        if value is not None:
            options[key] = value
    return AudioItem(
        src=audio.src,
        source=(SourceSpan(ref.locator, 0, len(ref.segment.text)),),
        options=options,
    )


def _apply_initial_capacity(
    speech: SpeechItem, index: SourceSegmentIndex, profile: RenderProfile
) -> list[FlowItem]:
    role = profile.roles[speech.role]
    capacity = role.planner_capacity
    if capacity is None:
        return [speech]
    if capacity.metric not in {"characters", "linguistic_tokens"}:
        raise RenderPlanProjectionError(
            f"UtterPlan cannot enforce planner capacity metric {capacity.metric!r}",
            code="renderplan.capacity.metric",
        )
    measured = _measure(index, speech.source, capacity.metric)
    if measured is None:
        if capacity.guarantee == "hard":
            raise _unsplittable(speech, capacity.metric, None, capacity.maximum)
        return [speech]
    if measured <= capacity.maximum:
        return [speech]
    result = _fit_capacity(speech, index, profile, capacity.metric, capacity.maximum, 0)
    oversized = [
        item
        for item in result
        if isinstance(item, SpeechItem)
        and (
            (value := _measure(index, item.source, capacity.metric)) is None
            or value > capacity.maximum
        )
    ]
    if oversized and capacity.guarantee == "hard":
        value = _measure(index, oversized[0].source, capacity.metric)
        raise _unsplittable(oversized[0], capacity.metric, value, capacity.maximum)
    return result


def _fit_capacity(
    speech: SpeechItem,
    index: SourceSegmentIndex,
    profile: RenderProfile,
    metric: str,
    maximum: int,
    fallback_index: int,
) -> list[FlowItem]:
    measured = _measure(index, speech.source, metric)
    if measured is not None and measured <= maximum:
        return [speech]
    fallbacks = profile.planning.capacity_fallback
    if fallback_index >= len(fallbacks):
        return [speech]
    fallback = fallbacks[fallback_index]
    if fallback == "clause":
        chunks = _clause_chunks(index, speech)
        if len(chunks) <= 1:
            return _fit_capacity(speech, index, profile, metric, maximum, fallback_index + 1)
        result: list[FlowItem] = []
        for chunk_index, source in enumerate(chunks):
            semantic_end = _semantic_end_at_source_end(index, source)
            if chunk_index == len(chunks) - 1 and semantic_end == "none":
                semantic_end = speech.semantic_end
            child = _child_speech(
                speech,
                index,
                source,
                profile,
                planning_level="clause",
                split_reason="capacity",
                semantic_end=semantic_end,
            )
            result.extend(_fit_capacity(child, index, profile, metric, maximum, fallback_index + 1))
            if chunk_index < len(chunks) - 1:
                result.append(
                    _capacity_pause_at_offset(
                        index,
                        speech.source,
                        sum(end - start for _, start, end in index.ordered_slices(source)),
                        profile,
                    )
                )
        return result
    if fallback == "token":
        split = _token_bisect(speech, index, profile)
        if split is None:
            return [speech]
        left, right, offset = split
        return [
            *_fit_capacity(left, index, profile, metric, maximum, fallback_index),
            _capacity_pause_at_offset(index, speech.source, offset, profile),
            *_fit_capacity(right, index, profile, metric, maximum, fallback_index),
        ]
    raise RenderPlanProjectionError(
        f"unsupported planner fallback {fallback!r}",
        code="renderplan.capacity.fallback",
    )


def _token_bisect(
    speech: SpeechItem, index: SourceSegmentIndex, profile: RenderProfile
) -> tuple[SpeechItem, SpeechItem, int] | None:
    cuts = _legal_token_cuts(index, speech.source)
    if not cuts:
        return None
    tokens = index.tokens_for(speech.source)
    total_tokens = len(tokens.span) if tokens is not None else 0
    if total_tokens < 2:
        return None
    chosen = min(
        cuts,
        key=lambda cut: (
            abs(_token_count_before(index, speech.source, cut) * 2 - total_tokens),
            cut,
        ),
    )
    left_source, right_source = _split_source(index, speech.source, chosen)
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
    return left, right, chosen


def _measure(index: SourceSegmentIndex, source: Sequence[SourceSpan], metric: str) -> int | None:
    if metric == "characters":
        return len(index.text_for(source))
    if metric != "linguistic_tokens":
        raise RenderPlanProjectionError(
            f"unsupported portable planner metric {metric!r}",
            code="renderplan.capacity.metric",
        )
    slices = index.ordered_slices(source)
    any_tokens = False
    for ref, start, end in slices:
        intersecting = [
            token for token in ref.segment.tokens if token.end > start and token.start < end
        ]
        if intersecting:
            any_tokens = True
        elif ref.segment.text[start:end].strip():
            return None
    if not any_tokens:
        return None
    bundle = index.tokens_for(source)
    return len(bundle.span) if bundle is not None else None


def _clause_chunks(
    index: SourceSegmentIndex, speech: SpeechItem
) -> tuple[tuple[SourceSpan, ...], ...]:
    offsets = _semantic_cut_offsets(index, speech.source)
    if not offsets:
        return (speech.source,)
    return _partition_source(index, speech.source, offsets)


def _semantic_cut_offsets(
    index: SourceSegmentIndex, source: Sequence[SourceSpan]
) -> tuple[int, ...]:
    offsets: list[int] = []
    cumulative = 0
    previous: tuple[SourceSegmentRef, int, int] | None = None
    for ref, start, end in index.ordered_slices(source):
        if previous is not None:
            left_ref, _, left_end = previous
            adjacent = (
                left_ref.locator != ref.locator
                and left_end == len(left_ref.segment.text)
                and start == 0
                and index._order_by_locator[ref.locator]
                == index._order_by_locator[left_ref.locator] + 1
            )
            boundary = _boundary_kind(left_ref.segment, ref.segment) if adjacent else "none"
            if boundary in {"clause", "sentence", "paragraph"}:
                offsets.append(cumulative)
        cumulative += end - start
        previous = (ref, start, end)
    return tuple(offsets)


def _partition_source(
    index: SourceSegmentIndex, source: Sequence[SourceSpan], offsets: Sequence[int]
) -> tuple[tuple[SourceSpan, ...], ...]:
    chunks: list[tuple[SourceSpan, ...]] = []
    remainder: Sequence[SourceSpan] = tuple(source)
    previous = 0
    for offset in sorted(set(offsets)):
        left, remainder = _split_source(index, remainder, offset - previous)
        if left:
            chunks.append(tuple(left))
        previous = offset
    if remainder:
        chunks.append(tuple(remainder))
    return tuple(chunks)


def _split_source(
    index: SourceSegmentIndex, source: Sequence[SourceSpan], offset: int
) -> tuple[list[SourceSpan], list[SourceSpan]]:
    total = sum(end - start for _, start, end in index.ordered_slices(source))
    if offset <= 0 or offset >= total:
        return [], list(source)
    left: list[SourceSpan] = []
    right: list[SourceSpan] = []
    remaining = offset
    passed = False
    for span in source:
        width = span.end - span.start
        if passed:
            right.append(span)
        elif remaining >= width:
            left.append(span)
            remaining -= width
        else:
            cut = span.start + remaining
            if cut > span.start:
                left.append(SourceSpan(span.locator, span.start, cut))
            if cut < span.end:
                right.append(SourceSpan(span.locator, cut, span.end))
            passed = True
            remaining = 0
    return left, right


def _legal_token_cuts(index: SourceSegmentIndex, source: Sequence[SourceSpan]) -> tuple[int, ...]:
    candidates: set[int] = set()
    protected: list[tuple[int, int]] = []
    offset = 0
    for ref, start, end in index.ordered_slices(source):
        for token in ref.segment.tokens:
            if token.end <= start or token.start >= end:
                continue
            candidates.add(offset + token.start - start)
            candidates.add(offset + token.end - start)
        for replacement in ref.segment.replacements:
            if replacement.end > start and replacement.start < end:
                protected.append(
                    (
                        offset + max(start, replacement.start) - start,
                        offset + min(end, replacement.end) - start,
                    )
                )
        if (
            ref.segment.directives.pronunciation is not None
            or ref.segment.directives.say_as is not None
        ):
            protected.append((offset, offset + end - start))
        offset += end - start
    total = offset
    return tuple(
        cut
        for cut in sorted(candidates)
        if 0 < cut < total and not any(start < cut < end for start, end in protected)
    )


def _token_count_before(index: SourceSegmentIndex, source: Sequence[SourceSpan], cut: int) -> int:
    left, _ = _split_source(index, source, cut)
    bundle = index.tokens_for(left)
    return len(bundle.span) if bundle is not None else 0


def _semantic_end_at_source_end(index: SourceSegmentIndex, source: Sequence[SourceSpan]) -> str:
    slices = index.ordered_slices(source)
    if not slices:
        return "none"
    ref, _, end = slices[-1]
    if end != len(ref.segment.text):
        return "none"
    position = index._order_by_locator[ref.locator]
    if position + 1 >= len(index.ordered_refs):
        return "none"
    return _boundary_kind(ref.segment, index.ordered_refs[position + 1].segment)


def _capacity_pause_at_offset(
    index: SourceSegmentIndex,
    source: Sequence[SourceSpan],
    cut: int,
    profile: RenderProfile,
) -> PauseItem:
    left, right = _split_source(index, source, cut)
    if left and right:
        left_ref, _, left_end = index.ordered_slices(left)[-1]
        right_ref, right_start, _ = index.ordered_slices(right)[0]
        adjacent = (
            left_ref.locator != right_ref.locator
            and left_end == len(left_ref.segment.text)
            and right_start == 0
            and index._order_by_locator[right_ref.locator]
            == index._order_by_locator[left_ref.locator] + 1
        )
        if adjacent:
            pause = _resolve_pause(
                _pause_intent(left_ref.segment.pause_after, left_ref.locator),
                _pause_intent(right_ref.segment.pause_before, right_ref.locator),
                semantic_end=None,
                profile=profile,
                capacity_cut=False,
            )
            if pause is not None:
                return pause
    return PauseItem(0, "capacity")


def _child_speech(
    parent: SpeechItem,
    index: SourceSegmentIndex,
    source: Sequence[SourceSpan],
    profile: RenderProfile,
    *,
    planning_level: str,
    split_reason: str,
    semantic_end: str,
) -> SpeechItem:
    role_profile = profile.roles[parent.role]
    return replace(
        parent,
        number=1,
        text=index.text_for(source),
        source=tuple(source),
        planning_level=planning_level,
        split_reason=split_reason,
        semantic_end=semantic_end
        if semantic_end in {"clause", "sentence", "paragraph", "parenthetical", "voice_change"}
        else "none",
        tokens=index.tokens_for(source, required_fields=role_profile.requirements.token_fields),
        controls=index.controls_for(source),
        segment_id=None,
    )


def _unsplittable(
    speech: SpeechItem, metric: str, measured: int | None, maximum: int
) -> RenderPlanProjectionError:
    source = ", ".join(f"{span.locator}[{span.start}:{span.end}]" for span in speech.source)
    return RenderPlanProjectionError(
        f"capacity cannot be satisfied for speech {speech.number} "
        f"({speech.segment_id or speech.computed_id()}), source={source}, "
        f"level={speech.planning_level}, metric={metric}, measured={measured}, maximum={maximum}",
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


__all__ = ["group_initial_plan"]
