"""Pure, renderer-neutral projections of saved FlowPlans into downstream chunks."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from .boundaries import BoundaryKind, canonicalize_boundary_kinds
from .model import FlowPlan, FlowSegment, PauseIntent

ChunkMode = Literal["segment", "clause", "sentence", "paragraph"]
PausePolicy = Literal["native", "automatic", "manual"]

_SELECTOR_ITEM = re.compile(r"(?:\d+|\d+-\d+)\Z")


@dataclass(frozen=True, slots=True)
class SegmentRef:
    """A stable zero-based location for one saved segment in flow order."""

    global_index: int
    unit_index: int
    local_index: int

    def to_dict(self) -> dict[str, int]:
        return {
            "global_index": self.global_index,
            "unit_index": self.unit_index,
            "local_index": self.local_index,
        }


@dataclass(frozen=True, slots=True)
class PreviewChunk:
    """A read-only projection of one or more stored segments."""

    index: int
    text: str
    segments: tuple[SegmentRef, ...]
    boundary_before: tuple[BoundaryKind, ...]
    boundary_after: tuple[BoundaryKind, ...]
    authored_pause_before: PauseIntent | None
    authored_pause_after: PauseIntent | None
    automatic_pause: str | None

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-compatible data without rewriting local plan spans."""
        return {
            "index": self.index,
            "text": self.text,
            "segments": [item.to_dict() for item in self.segments],
            "boundary_before": list(self.boundary_before),
            "boundary_after": list(self.boundary_after),
            "authored_pause_before": (
                self.authored_pause_before.to_dict()
                if self.authored_pause_before is not None
                else None
            ),
            "authored_pause_after": (
                self.authored_pause_after.to_dict()
                if self.authored_pause_after is not None
                else None
            ),
            "automatic_pause": self.automatic_pause,
        }


@dataclass(frozen=True, slots=True)
class _IndexedSegment:
    ref: SegmentRef
    segment: FlowSegment


def resolve_segment_selector(selector: str | None, segment_count: int) -> frozenset[int] | None:
    """Resolve a zero-based ``N,N-M,...`` selector; ``None`` means all segments."""
    if type(segment_count) is not int or segment_count < 0:
        raise ValueError("segment_count must be a non-negative integer")
    if selector is None or selector == "all":
        return None
    if not isinstance(selector, str) or not selector.strip():
        raise ValueError("segment selector must be a non-empty selector or 'all'")

    selected: set[int] = set()
    for raw_item in selector.split(","):
        item = raw_item.strip()
        if not item or _SELECTOR_ITEM.fullmatch(item) is None:
            raise ValueError(f"invalid segment selector item: {raw_item!r}")
        indexes: Sequence[int]
        if "-" in item:
            first_text, last_text = item.split("-", 1)
            first, last = int(first_text), int(last_text)
            if first > last:
                raise ValueError(f"segment range is reversed: {item!r}")
            indexes = range(first, last + 1)
        else:
            indexes = (int(item),)
        for index in indexes:
            if index >= segment_count:
                raise ValueError(
                    f"segment index {index} is out of range for {segment_count} stored segments"
                )
            selected.add(index)
    return frozenset(selected)


def preview_plan(
    plan: FlowPlan,
    *,
    segments: str | None = None,
    chunk_by: ChunkMode = "sentence",
    pause_policy: PausePolicy = "native",
) -> tuple[PreviewChunk, ...]:
    """Project a saved plan into chunks without changing its stored content or identity.

    Chunk grouping and pause realization are independent. Selection indexes refer to
    the global zero-based flow-order segment list, and selected segments retain their
    complete containing chunks.
    """
    if chunk_by not in {"segment", "clause", "sentence", "paragraph"}:
        raise ValueError(f"unsupported chunk mode: {chunk_by!r}")
    if pause_policy not in {"native", "automatic", "manual"}:
        raise ValueError(f"unsupported pause policy: {pause_policy!r}")

    indexed = tuple(
        _IndexedSegment(SegmentRef(global_index, unit_index, local_index), segment)
        for global_index, (unit_index, local_index, segment) in enumerate(
            (unit_index, local_index, segment)
            for unit_index, unit in enumerate(plan.flow)
            for local_index, segment in enumerate(unit.segments)
        )
    )
    focus = resolve_segment_selector(segments, len(indexed))
    groups = _group_segments(indexed, chunk_by)
    result: list[PreviewChunk] = []
    for group in groups:
        first_index = group[0].ref.global_index
        last_index = group[-1].ref.global_index
        before = (
            _edge_boundaries(indexed[first_index - 1], group[0])
            if first_index
            else canonicalize_boundary_kinds(group[0].segment.boundary_before)
        )
        after = (
            _edge_boundaries(group[-1], indexed[last_index + 1])
            if last_index + 1 < len(indexed)
            else canonicalize_boundary_kinds(group[-1].segment.boundary_after)
        )
        authored_before = _authored_pause_at_edge(
            indexed[first_index - 1] if first_index else None, group[0]
        )
        authored_after = _authored_pause_at_edge(
            group[-1], indexed[last_index + 1] if last_index + 1 < len(indexed) else None
        )
        automatic_pause = _automatic_pause(
            after,
            pause_policy=pause_policy,
            authored_pause=authored_after,
            at_plan_end=last_index == len(indexed) - 1,
        )
        chunk = PreviewChunk(
            index=len(result),
            text="".join(item.segment.text for item in group),
            segments=tuple(item.ref for item in group),
            boundary_before=before,
            boundary_after=after,
            authored_pause_before=authored_before,
            authored_pause_after=authored_after,
            automatic_pause=automatic_pause,
        )
        if focus is None or any(item.global_index in focus for item in chunk.segments):
            result.append(chunk)
    return tuple(result)


def _group_segments(
    indexed: tuple[_IndexedSegment, ...], chunk_by: ChunkMode
) -> tuple[tuple[_IndexedSegment, ...], ...]:
    if chunk_by == "segment":
        return tuple((item,) for item in indexed)
    if chunk_by == "paragraph":
        by_unit: dict[int, list[_IndexedSegment]] = {}
        for item in indexed:
            by_unit.setdefault(item.ref.unit_index, []).append(item)
        return tuple(tuple(by_unit[index]) for index in sorted(by_unit))

    groups: list[tuple[_IndexedSegment, ...]] = []
    current: list[_IndexedSegment] = []
    closing_kinds = (
        {"clause", "sentence", "paragraph"} if chunk_by == "clause" else {"sentence", "paragraph"}
    )
    for index, item in enumerate(indexed):
        current.append(item)
        if index + 1 < len(indexed) and closing_kinds.intersection(
            _edge_boundaries(item, indexed[index + 1])
        ):
            groups.append(tuple(current))
            current = []
    if current:
        groups.append(tuple(current))
    return tuple(groups)


def _edge_boundaries(
    previous: _IndexedSegment, following: _IndexedSegment
) -> tuple[BoundaryKind, ...]:
    values = (*previous.segment.boundary_after, *following.segment.boundary_before)
    if previous.ref.unit_index != following.ref.unit_index:
        values = (*values, "paragraph")
    return canonicalize_boundary_kinds(values)


def _authored_pause_at_edge(
    previous: _IndexedSegment | None, following: _IndexedSegment | None
) -> PauseIntent | None:
    after = previous.segment.pause_after if previous is not None else None
    before = following.segment.pause_before if following is not None else None
    if isinstance(before, PauseIntent):
        return before
    if isinstance(after, PauseIntent):
        return after
    return None


def _automatic_pause(
    boundary_after: tuple[BoundaryKind, ...],
    *,
    pause_policy: PausePolicy,
    authored_pause: PauseIntent | None,
    at_plan_end: bool,
) -> str | None:
    if pause_policy == "native":
        return None
    if authored_pause is not None and authored_pause.type == "none":
        return None
    if pause_policy == "automatic" and authored_pause is not None:
        return None

    available = set(boundary_after)
    if at_plan_end:
        # End-of-flow is an implicit sentence-completion edge; no punctuation scan is needed.
        available.add("sentence")
    for kind in ("paragraph", "sentence", "clause"):
        if kind in available:
            return kind
    return None


__all__ = [
    "ChunkMode",
    "PausePolicy",
    "PreviewChunk",
    "SegmentRef",
    "preview_plan",
    "resolve_segment_selector",
]
