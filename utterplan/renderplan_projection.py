"""Schema-v7 source indexing and exact RenderPlan projection primitives.

This module deliberately consumes the public UtterPlan model. It does not parse
serialized plans, prepare text, or depend on renderer implementations.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import Any

from renderplan import SourceSpan, SpeechControl, TokenBundle

from .model import (
    EmphasisDirective,
    ExtensionDirective,
    FlowPlan,
    FlowSegment,
    LegacyFlowPlan,
    PronunciationDirective,
    ProsodyDirective,
    SayAsDirective,
    SegmentDirectives,
    TokenView,
)
from .versioning import CURRENT_SCHEMA_VERSION


class RenderPlanProjectionError(ValueError):
    """A current UtterPlan semantic cannot be projected into RenderPlan safely."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "renderplan.projection.invalid",
        locator: str | None = None,
        token_index: int | None = None,
    ) -> None:
        self.code = code
        self.locator = locator
        self.token_index = token_index
        location = f" at {locator}" if locator is not None else ""
        if token_index is not None:
            location += f" token index {token_index}"
        super().__init__(f"{code}{location}: {message}")


@dataclass(frozen=True, slots=True)
class SourceSegmentRef:
    """A stable v7 flow locator bound to one source plan's segment position."""

    locator: str
    flow_index: int
    segment_index: int
    segment: FlowSegment


@dataclass(frozen=True, slots=True)
class SourceSegmentIndex:
    """Immutable ordered source view shared by projection and replanning stages."""

    source_plan_id: str
    ordered_refs: tuple[SourceSegmentRef, ...]
    by_locator: Mapping[str, SourceSegmentRef]
    _order_by_locator: Mapping[str, int]

    def resolve(self, locator: str) -> SourceSegmentRef:
        try:
            return self.by_locator[locator]
        except KeyError as exc:
            raise RenderPlanProjectionError(
                f"source locator {locator!r} does not resolve in plan {self.source_plan_id}",
                code="renderplan.source.locator",
                locator=locator,
            ) from exc

    def ordered_slices(
        self, source: Sequence[SourceSpan]
    ) -> tuple[tuple[SourceSegmentRef, int, int], ...]:
        """Resolve and validate ordered, non-overlapping spans in prepared-text coordinates."""
        resolved: list[tuple[SourceSegmentRef, int, int]] = []
        previous_order = -1
        previous_end = -1
        for span in source:
            if not isinstance(span, SourceSpan):
                raise RenderPlanProjectionError(
                    "source entries must be RenderPlan SourceSpan values",
                    code="renderplan.source.span_type",
                )
            ref = self.resolve(span.locator)
            order = self._order_by_locator[span.locator]
            if order < previous_order or (order == previous_order and span.start < previous_end):
                raise RenderPlanProjectionError(
                    "source spans must follow non-overlapping UtterPlan flow order",
                    code="renderplan.source.order",
                    locator=span.locator,
                )
            if span.end > len(ref.segment.text):
                raise RenderPlanProjectionError(
                    f"source range [{span.start}:{span.end}] exceeds prepared segment length "
                    f"{len(ref.segment.text)}",
                    code="renderplan.source.range",
                    locator=span.locator,
                )
            resolved.append((ref, span.start, span.end))
            previous_order = order
            previous_end = span.end
        return tuple(resolved)

    def text_for(self, source: Sequence[SourceSpan]) -> str:
        """Concatenate exact prepared source slices; whitespace is never normalized."""
        return "".join(
            ref.segment.text[start:end] for ref, start, end in self.ordered_slices(source)
        )

    def tokens_for(
        self,
        source: Sequence[SourceSpan],
        *,
        required_fields: Iterable[str] = (),
    ) -> TokenBundle | None:
        """Project complete source tokens into request-local coordinates."""
        required = frozenset(required_fields)
        unknown = required.difference({"span", "pos", "tag", "lemma", "morph"})
        if unknown:
            raise RenderPlanProjectionError(
                f"unsupported required token fields: {', '.join(sorted(unknown))}",
                code="renderplan.token.requirement",
            )

        projected: list[tuple[TokenView, str, int]] = []
        slices = self.ordered_slices(source)
        for ref, start, end in slices:
            for token_index, token in enumerate(ref.segment.tokens):
                if token.end <= start or token.start >= end:
                    continue
                if token.start < start or token.end > end:
                    raise RenderPlanProjectionError(
                        f"source range [{start}:{end}] cuts token [{token.start}:{token.end}]",
                        code="renderplan.token.split",
                        locator=ref.locator,
                        token_index=token_index,
                    )
                projected.append((token, ref.locator, token_index))

        if not projected:
            if required:
                locator = source[0].locator if source else None
                raise RenderPlanProjectionError(
                    "required token fields are unavailable because the source slice has no tokens",
                    code="renderplan.token.required",
                    locator=locator,
                    token_index=0,
                )
            return None

        for token, locator, token_index in projected:
            for field_name in required:
                value = token_field_value(token, field_name)
                if value is None or (isinstance(value, str) and not value.strip()):
                    raise RenderPlanProjectionError(
                        f"required token field {field_name!r} is unavailable",
                        code="renderplan.token.required",
                        locator=locator,
                        token_index=token_index,
                    )

        spans: list[tuple[int, int]] = []
        pos: list[str] = []
        tag: list[str] = []
        lemma: list[tuple[int, str]] = []
        morph: list[tuple[int, str]] = []
        request_offset = 0
        token_index = 0
        for ref, start, end in slices:
            for local_index, token in enumerate(ref.segment.tokens):
                if token.end <= start or token.start >= end:
                    continue
                spans.append(
                    (request_offset + token.start - start, request_offset + token.end - start)
                )
                if any(item.pos is not None for item, _, _ in projected):
                    pos.append(token.pos or "")
                if any(item.tag is not None for item, _, _ in projected):
                    tag.append(token.tag or "")
                if token.lemma is not None:
                    if not token.lemma:
                        raise RenderPlanProjectionError(
                            "empty lemma cannot be represented by RenderPlan",
                            code="renderplan.token.value",
                            locator=ref.locator,
                            token_index=local_index,
                        )
                    lemma.append((token_index, token.lemma))
                if token.morph is not None:
                    if not token.morph:
                        raise RenderPlanProjectionError(
                            "empty morph cannot be represented by RenderPlan",
                            code="renderplan.token.value",
                            locator=ref.locator,
                            token_index=local_index,
                        )
                    morph.append((token_index, token.morph))
                token_index += 1
            request_offset += end - start

        return TokenBundle(
            span=tuple(spans),
            pos=tuple(pos),
            tag=tuple(tag),
            lemma=tuple(lemma),
            morph=tuple(morph),
        )

    def controls_for(self, source: Sequence[SourceSpan]) -> tuple[SpeechControl, ...]:
        """Project renderer-neutral directives into request-local control ranges."""
        controls: list[SpeechControl] = []
        request_offset = 0
        for ref, start, end in self.ordered_slices(source):
            width = end - start
            for name, params in _speech_directives(ref.segment.directives, ref.locator):
                candidate = SpeechControl(
                    start=request_offset,
                    end=request_offset + width,
                    name=name,
                    params=params,
                )
                if (
                    controls
                    and controls[-1].end == candidate.start
                    and controls[-1].name == candidate.name
                    and dict(controls[-1].params) == dict(candidate.params)
                ):
                    previous = controls.pop()
                    controls.append(
                        SpeechControl(
                            start=previous.start,
                            end=candidate.end,
                            name=previous.name,
                            params=previous.params,
                        )
                    )
                else:
                    controls.append(candidate)
            request_offset += width
        return tuple(sorted(controls, key=lambda control: control.ordering_key()))


def build_source_index(plan: FlowPlan) -> SourceSegmentIndex:
    """Index all current schema-v7 flow segments exactly once in serialized order."""
    if isinstance(plan, LegacyFlowPlan):
        raise RenderPlanProjectionError(
            f"RenderPlan export requires UtterPlan schema version {CURRENT_SCHEMA_VERSION}; "
            f"received legacy schema version {plan.schema_version}",
            code="renderplan.source.schema_version",
        )
    if not isinstance(plan, FlowPlan):
        raise RenderPlanProjectionError(
            "RenderPlan export requires an utterplan.model.FlowPlan",
            code="renderplan.source.plan_type",
        )
    if plan.schema_version != CURRENT_SCHEMA_VERSION:
        raise RenderPlanProjectionError(
            f"RenderPlan export requires UtterPlan schema version {CURRENT_SCHEMA_VERSION}; "
            f"received {plan.schema_version}",
            code="renderplan.source.schema_version",
        )

    refs: list[SourceSegmentRef] = []
    for flow_index, unit in enumerate(plan.flow):
        for segment_index, segment in enumerate(unit.segments):
            refs.append(
                SourceSegmentRef(
                    locator=f"f{flow_index:06d}.s{segment_index:03d}",
                    flow_index=flow_index,
                    segment_index=segment_index,
                    segment=segment,
                )
            )
    by_locator = {ref.locator: ref for ref in refs}
    order_by_locator = {ref.locator: index for index, ref in enumerate(refs)}
    return SourceSegmentIndex(
        source_plan_id=plan.plan_id,
        ordered_refs=tuple(refs),
        by_locator=MappingProxyType(by_locator),
        _order_by_locator=MappingProxyType(order_by_locator),
    )


def token_field_value(token: TokenView, field_name: str) -> str | tuple[int, int] | None:
    """Return one portable token fact for required-field validation."""
    if field_name == "span":
        return (token.start, token.end)
    if field_name in {"pos", "tag", "lemma", "morph"}:
        return getattr(token, field_name)
    return None


def _speech_directives(
    directives: SegmentDirectives, locator: str
) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    handled = {
        "voice",
        "pronunciation",
        "prosody",
        "emphasis",
        "audio",
        "say_as",
        "substitution",
        "extensions",
    }
    unexpected = [
        field.name
        for field in fields(directives)
        if field.name not in handled and getattr(directives, field.name) is not None
    ]
    if unexpected:
        raise RenderPlanProjectionError(
            f"unsupported UtterPlan execution directives: {', '.join(unexpected)}",
            code="renderplan.directive.unsupported",
            locator=locator,
        )

    projected: list[tuple[str, Mapping[str, Any]]] = []
    pronunciation = directives.pronunciation
    if isinstance(pronunciation, PronunciationDirective):
        projected.append(
            (
                "pronunciation",
                {"phonemes": pronunciation.phonemes, "alphabet": pronunciation.alphabet},
            )
        )
    prosody = directives.prosody
    if isinstance(prosody, ProsodyDirective):
        projected.append(("prosody", _non_null(prosody.to_dict())))
    emphasis = directives.emphasis
    if isinstance(emphasis, EmphasisDirective):
        projected.append(("emphasis", {"level": emphasis.level}))
    say_as = directives.say_as
    if isinstance(say_as, SayAsDirective):
        projected.append(("say_as", _non_null(say_as.to_dict())))
    for extension in directives.extensions:
        if not isinstance(extension, ExtensionDirective):
            raise RenderPlanProjectionError(
                "extension directive has an unsupported value",
                code="renderplan.directive.unsupported",
                locator=locator,
            )
        projected.append(("extension", {"name": extension.name, **dict(extension.params)}))

    # Voice is resolved as logical role state; audio is projected as an ordered
    # AudioItem by grouping; substitution has already affected prepared text.
    return tuple(projected)


def _non_null(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


__all__ = [
    "RenderPlanProjectionError",
    "SourceSegmentIndex",
    "SourceSegmentRef",
    "build_source_index",
    "token_field_value",
]
