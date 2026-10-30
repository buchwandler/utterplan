"""Public schema-v7 RenderPlan construction and single-model explanations."""

from __future__ import annotations

from collections.abc import Sequence

from renderplan import (
    AudioItem,
    PauseItem,
    PreflightReport,
    Producer,
    RenderPlan,
    RenderProfile,
    SourceSpan,
    SpeechItem,
)

from ._version import __version__
from .model import FlowPlan
from .renderplan_grouping import group_initial_plan
from .renderplan_pause_timing import PauseTimingConfig
from .renderplan_projection import RenderPlanProjectionError, build_source_index
from .renderplan_replan import replan_flow
from .role_coverage import assert_profile_role_coverage


def build_render_plan(
    utterplan: FlowPlan,
    profile: RenderProfile,
    *,
    previous_plan: RenderPlan | None = None,
    preflight: PreflightReport | None = None,
    pause_timing: PauseTimingConfig | None = None,
) -> RenderPlan:
    """Project a schema-v7 FlowPlan or refine its matching prior RenderPlan."""
    if not isinstance(profile, RenderProfile):
        raise RenderPlanProjectionError(
            "RenderPlan construction requires a RenderProfile",
            code="renderplan.profile.type",
        )
    index = build_source_index(utterplan)
    if (previous_plan is None) != (preflight is None):
        raise RenderPlanProjectionError(
            "replanning requires both previous_plan and preflight; omit both for an initial build",
            code="renderplan.replan.inputs",
        )
    if previous_plan is not None and pause_timing is not None:
        raise RenderPlanProjectionError(
            "pause_timing applies only to initial RenderPlan projection; replanning preserves "
            "pause timing from previous_plan",
            code="renderplan.replan.pause_timing",
        )
    assert_profile_role_coverage(utterplan, profile)
    profile_id = profile.profile_id or profile.computed_id()
    if previous_plan is None:
        flow = group_initial_plan(index, profile, pause_timing=pause_timing)
    else:
        assert preflight is not None
        flow = replan_flow(index, profile, previous_plan, preflight)

    result = RenderPlan(
        source_plan_id=index.source_plan_id,
        render_profile_id=profile_id,
        flow=flow,
        producer=Producer(name="utterplan", version=__version__),
    ).with_identity()
    result.validate_against_profile(profile)
    return result


def format_render_plan_explanation(
    plan: RenderPlan,
    *,
    previous_plan: RenderPlan | None = None,
    preflight: PreflightReport | None = None,
) -> str:
    """Format decisions from an already generated plan without running planning."""
    if (previous_plan is None) != (preflight is None):
        raise ValueError("explanation requires both previous_plan and preflight, or neither")

    lines: list[str] = []
    if previous_plan is not None and preflight is not None:
        for request in preflight.replan:
            old = next(
                (
                    speech
                    for speech in previous_plan.speech
                    if speech.number == request.segment_number
                    and (speech.segment_id or speech.computed_id()) == request.segment_id
                ),
                None,
            )
            if old is None:
                continue
            children = tuple(
                speech for speech in plan.speech if _source_is_within(speech.source, request.source)
            )
            levels = tuple(dict.fromkeys(child.planning_level for child in children))
            lines.extend(
                (
                    f"replaced previous speech {request.segment_number}",
                    f"  {request.metric} {request.measured} > {request.maximum}",
                    f"  fallback {request.current_level} -> {', '.join(levels) or 'none'}",
                    f"  children: {', '.join(str(child.number) for child in children) or '-'}",
                    "",
                )
            )

    for position, item in enumerate(plan.flow):
        if isinstance(item, SpeechItem):
            lines.extend(
                _explain_speech(
                    item, plan.flow[position + 1] if position + 1 < len(plan.flow) else None
                )
            )
        elif isinstance(item, PauseItem):
            lines.append(f"pause {item.duration_ms}ms {item.reason}")
        elif isinstance(item, AudioItem):
            source = _format_source(item.source)
            lines.append(f"audio {item.src}\n  source: {source}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _explain_speech(
    speech: SpeechItem, following: AudioItem | PauseItem | SpeechItem | None
) -> list[str]:
    tokens = str(len(speech.tokens.span)) if speech.tokens is not None else "unavailable"
    controls = (
        ", ".join(f"{control.name}[{control.start}:{control.end}]" for control in speech.controls)
        or "-"
    )
    pause_after = (
        f"{following.duration_ms}ms {following.reason}"
        if isinstance(following, PauseItem)
        else "none"
    )
    return [
        f"speech {speech.number:06d}",
        f"  source: {_format_source(speech.source)}",
        f"  role: {speech.role}",
        f"  level: {speech.planning_level}",
        f"  end: {speech.semantic_end}",
        f"  reason: {speech.split_reason}",
        f"  tokens: {tokens}",
        f"  controls: {controls}",
        f"  pause-after: {pause_after}",
    ]


def _format_source(source: Sequence[SourceSpan]) -> str:
    return " + ".join(f"{span.locator}[{span.start}:{span.end}]" for span in source)


def _source_is_within(source: Sequence[SourceSpan], parent: Sequence[SourceSpan]) -> bool:
    if not source or not parent:
        return False
    return all(
        any(
            child.locator == container.locator
            and container.start <= child.start
            and child.end <= container.end
            for container in parent
        )
        for child in source
    )


__all__ = ["build_render_plan", "format_render_plan_explanation"]
