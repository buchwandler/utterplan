from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, cast

from .exceptions import PlanValidationError
from .model import (
    DocumentInfo,
    FlowPlan,
    FlowSegment,
    FlowUnit,
    LinguisticProvenance,
    PauseIntent,
    PlanSource,
    ReplacementView,
    TokenView,
    UtterancePlan,
)
from .token_topology import boundary_splits_lexical_content


def project_compiler_plan(plan: UtterancePlan) -> FlowPlan:
    """Project compiler-owned state into the current portable flow model."""
    _validate_replacement_ownership(plan)
    segments_by_id = {segment.id: segment for segment in plan.segments}
    markers_by_id = {marker.id: marker for marker in plan.markers}
    headings = _headings_by_segment(plan)
    token_providers = _token_providers(plan)
    markers_by_segment: dict[str, list[tuple[int, int, str]]] = {}

    for unit in plan.units:
        for marker_id in unit.marker_ids:
            marker = markers_by_id.get(marker_id)
            if marker is None:
                raise PlanValidationError(
                    "unit references an unknown marker", code="marker.unknown"
                )
            candidates = [
                segments_by_id[item] for item in unit.segment_ids if item in segments_by_id
            ]
            owner = _locate_segment(marker.spoken_position, candidates)
            if owner is None and candidates:
                owner = min(
                    candidates,
                    key=lambda item: min(
                        abs(marker.spoken_position - item.spoken_start),
                        abs(marker.spoken_position - item.spoken_end),
                    ),
                )
            if owner is None:
                raise PlanValidationError(
                    "marker has no owning flow segment", code="marker.unlocalized"
                )
            markers_by_segment.setdefault(owner.id, []).append(
                (marker.spoken_position, plan.markers.index(marker), marker.name)
            )

    flow: list[FlowUnit] = []
    for flow_index, unit in enumerate(plan.units):
        unit_segments: list[FlowSegment] = []
        for segment_index, segment_id in enumerate(unit.segment_ids):
            segment = segments_by_id.get(segment_id)
            if segment is None:
                raise PlanValidationError(
                    "unit references an unknown segment", code="unit.unknown_segment"
                )
            pause_before = _pause(segment.pause_before, "pause_before")
            pause_after = _pause(segment.pause_after, "pause_after")
            unit_segments.append(
                FlowSegment(
                    text=segment.text,
                    language=segment.language,
                    pause_before=pause_before,
                    pause_after=pause_after,
                    directives=segment.directives,
                    tokens=_tokens_for_segment(
                        plan,
                        segment,
                        token_providers,
                        f"$.flow[{flow_index}].segments[{segment_index}].tokens",
                    ),
                    markers=tuple(
                        name
                        for _position, _marker_index, name in sorted(
                            markers_by_segment.get(segment.id, ())
                        )
                    ),
                    heading=headings.get(segment.id),
                    replacements=_replacement_views_for_segment(plan, segment),
                )
            )
        flow.append(FlowUnit(tuple(unit_segments)))

    unit_kind = plan.units[0].kind if plan.units else plan.config.get("unit", "paragraph")
    if unit_kind not in {"sentence", "paragraph"}:
        raise PlanValidationError("unit must be sentence or paragraph", code="unit.invalid")
    return FlowPlan(
        language=str(plan.config.get("language", "")),
        unit=cast(Literal["sentence", "paragraph"], unit_kind),
        flow=tuple(flow),
        document=_document_info(plan),
        linguistics=_linguistic_info(plan),
        source=PlanSource(plan.source.format, plan.source.text),
        producer=_portable_producer(plan),
        warnings=(),
    )


def _pause(value: Any, field: str) -> PauseIntent | None:
    if value is None:
        return None
    if not isinstance(value, PauseIntent):
        raise PlanValidationError(
            f"fresh compiler {field} is not semantic pause intent",
            code="pause.invalid",
        )
    return value


def _tokens_for_segment(
    plan: UtterancePlan,
    segment: Any,
    token_providers: tuple[str | None, ...],
    projection_path: str,
) -> tuple[TokenView, ...]:
    result: list[TokenView] = []
    spoken = plan.texts.spoken
    for token_index in segment.token_indices:
        if type(token_index) is not int or not 0 <= token_index < len(plan.tokens):
            raise PlanValidationError("segment references an unknown token", code="token.unknown")
        token = plan.tokens[token_index]
        if spoken[token.spoken_start : token.spoken_end] != token.text:
            raise PlanValidationError(
                "token surface differs from spoken text", code="token.surface"
            )
        if token.language is not None and token.language != segment.language:
            raise PlanValidationError(
                "token language differs from its owning segment",
                code="token.language",
            )
        start = max(token.spoken_start, segment.spoken_start)
        end = min(token.spoken_end, segment.spoken_end)
        if start >= end:
            continue
        is_whole = start == token.spoken_start and end == token.spoken_end
        surface = spoken[start:end]
        provider = token_providers[token_index]
        if not is_whole:
            split_at_start = boundary_splits_lexical_content(start, token=token, provider=provider)
            split_at_end = boundary_splits_lexical_content(end, token=token, provider=provider)
            if split_at_start:
                raise PlanValidationError(
                    f"compiler segment {segment.id} "
                    f"[{segment.spoken_start}:{segment.spoken_end}] splits token "
                    f"{token_index} [{token.spoken_start}:{token.spoken_end}] at its start",
                    code="token.segment_split",
                    path=projection_path,
                )
            if split_at_end:
                raise PlanValidationError(
                    f"compiler segment {segment.id} "
                    f"[{segment.spoken_start}:{segment.spoken_end}] splits token "
                    f"{token_index} [{token.spoken_start}:{token.spoken_end}] at its end",
                    code="token.segment_split",
                    path=projection_path,
                )
            if not _has_word_character(surface):
                # Punctuation-only fragments at semantic boundaries remain in text, not token facts.
                continue
        lemma = token.lemma
        if not is_whole and (
            lemma == token.text.casefold()
            or (provider == "fallback" and lemma == token.text.lower())
        ):
            lemma = surface.casefold()
        result.append(
            TokenView(
                start=start - segment.spoken_start,
                end=end - segment.spoken_start,
                lemma=lemma,
                pos=token.pos,
                tag=token.tag,
                morph=token.morph,
            )
        )
    return tuple(result)


def _replacement_owner(plan: UtterancePlan, raw: Any, index: int) -> Any:
    path = f"$.preparation.replacements[{index}]"
    if not isinstance(raw, Mapping):
        raise PlanValidationError(
            "replacement provenance must be an object", code="replacement.type", path=path
        )
    output_start, output_end = raw.get("output_start"), raw.get("output_end")
    source_start, source_end = raw.get("source_start"), raw.get("source_end")
    source, replacement = raw.get("source"), raw.get("replacement")
    if (
        type(output_start) is not int
        or type(output_end) is not int
        or not 0 <= output_start <= output_end <= len(plan.texts.spoken)
        or type(source_start) is not int
        or type(source_end) is not int
        or not 0 <= source_start < source_end <= len(plan.texts.structural)
        or not isinstance(source, str)
        or not isinstance(replacement, str)
        or plan.texts.structural[source_start:source_end] != source
        or plan.texts.spoken[output_start:output_end] != replacement
    ):
        raise PlanValidationError(
            "replacement provenance ranges or surfaces cannot be verified",
            code="replacement.provenance",
            path=path,
        )
    kind, rule = raw.get("kind"), raw.get("rule")
    if (kind is not None and (not isinstance(kind, str) or not kind)) or (
        rule is not None and (not isinstance(rule, str) or not rule)
    ):
        raise PlanValidationError(
            "replacement kind/rule must be non-empty strings",
            code="replacement.provenance",
            path=path,
        )
    if output_start < output_end:
        owners = [
            segment
            for segment in plan.segments
            if segment.spoken_start <= output_start and output_end <= segment.spoken_end
        ]
    else:
        owners = [
            segment
            for segment in plan.segments
            if segment.spoken_start <= output_start < segment.spoken_end
        ]
        if not owners and output_start == len(plan.texts.spoken):
            owners = [segment for segment in plan.segments if segment.spoken_end == output_start]
    if len(owners) != 1:
        raise PlanValidationError(
            f"replacement provenance must have exactly one owning segment; found {len(owners)}",
            code="replacement.owner",
            path=path,
        )
    return owners[0]


def _validate_replacement_ownership(plan: UtterancePlan) -> None:
    for index, raw in enumerate(plan.preparation.replacements):
        _replacement_owner(plan, raw, index)


def _replacement_views_for_segment(
    plan: UtterancePlan, segment: Any
) -> tuple[ReplacementView, ...]:
    views: list[ReplacementView] = []
    for index, raw in enumerate(plan.preparation.replacements):
        owner = _replacement_owner(plan, raw, index)
        if owner.id != segment.id:
            continue
        output_start = raw["output_start"]
        output_end = raw["output_end"]
        views.append(
            ReplacementView(
                start=output_start - segment.spoken_start,
                end=output_end - segment.spoken_start,
                source=raw["source"],
                kind=raw.get("kind"),
                rule=raw.get("rule"),
            )
        )
    return tuple(sorted(views, key=lambda item: (item.start, item.end, item.source)))


def _has_word_character(value: str) -> bool:
    return any(character.isalnum() for character in value)


def _token_providers(plan: UtterancePlan) -> tuple[str | None, ...]:
    providers: list[str | None] = [None] * len(plan.tokens)
    for run in plan.linguistic_runs:
        for token_index in range(run.token_start, run.token_end):
            providers[token_index] = run.provider
    return tuple(providers)


def _locate_segment(
    position: int, segments: list[Any], *, prefer_start: bool = False
) -> Any | None:
    candidates: list[tuple[tuple[int, int, int], Any]] = []
    for index, segment in enumerate(segments):
        start, end = segment.spoken_start, segment.spoken_end
        if prefer_start and position == start:
            candidates.append(((0, end - start, index), segment))
        elif not prefer_start and position == end:
            candidates.append(((0, -end, index), segment))
        elif start < position < end:
            candidates.append(((1, end - start, index), segment))
        elif position == (end if prefer_start else start):
            candidates.append(((2, end - start, index), segment))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def _headings_by_segment(plan: UtterancePlan) -> dict[str, int]:
    result: dict[str, int] = {}
    for boundary in plan.boundaries:
        if boundary.kind != "heading":
            continue
        prefer_start = boundary.attrs.get("anchor") == "before"
        segment = _locate_segment(
            boundary.position,
            list(plan.segments),
            prefer_start=prefer_start,
        )
        if segment is None:
            raise PlanValidationError(
                "heading has no owning flow segment", code="heading.unlocalized"
            )
        level = boundary.attrs.get("level")
        if isinstance(level, str) and level.isdigit():
            level = int(level)
        if type(level) is not int or level < 1:
            raise PlanValidationError("heading level must be positive", code="heading.level")
        previous = result.get(segment.id)
        if previous is not None and previous != level:
            raise PlanValidationError(
                "multiple heading levels share one segment", code="heading.conflict"
            )
        result[segment.id] = level
    return result


def _document_info(plan: UtterancePlan) -> DocumentInfo:
    metadata = plan.document_metadata
    header_value = metadata.get("header", {})
    header = header_value if isinstance(header_value, Mapping) else {}
    semantics: dict[str, Any] = {}
    for key in ("voice_bindings", "prosody_transitions", "requires"):
        value = metadata.get(key, header.get(key))
        if value is not None:
            semantics[key] = value
    for values in (metadata, header):
        for key, value in values.items():
            if isinstance(key, str) and key.startswith("x-"):
                semantics[key] = value
    return DocumentInfo(
        format=plan.source.format,
        ssmd_version=_metadata_string(metadata, header, "ssmd_version"),
        title=_metadata_string(metadata, header, "title"),
        semantics=semantics,
    )


def _metadata_string(
    metadata: Mapping[str, Any], header: Mapping[str, Any], key: str
) -> str | None:
    value = metadata.get(key, header.get(key))
    return value if isinstance(value, str) and value else None


def _linguistic_info(plan: UtterancePlan) -> tuple[LinguisticProvenance, ...]:
    languages = {run.id: run.language for run in plan.languages}
    result: list[LinguisticProvenance] = []
    seen: set[tuple[Any, ...]] = set()
    for run in plan.linguistic_runs:
        language = languages.get(run.language_run_id)
        if language is None:
            raise PlanValidationError(
                "linguistic provenance has no language", code="linguistics.language"
            )
        identity = (
            language,
            run.provider,
            run.model,
            run.provider_version,
            run.model_version,
        )
        if identity in seen:
            continue
        result.append(
            LinguisticProvenance(
                language=language,
                provider=run.provider,
                model=run.model,
                provider_version=run.provider_version,
                model_version=run.model_version,
            )
        )
        seen.add(identity)
    return tuple(result)


def _portable_producer(plan: UtterancePlan) -> dict[str, str]:
    producer = _small_producer(plan.producer)
    mode = plan.config.get("text_preparation")
    if isinstance(mode, str) and mode in {"ssmd", "spokenform", "identity"}:
        producer["text_preparation"] = mode
    return producer


def _small_producer(value: Mapping[str, Any]) -> dict[str, str]:
    return {key: value[key] for key in ("name", "version") if isinstance(value.get(key), str)}


__all__ = ["project_compiler_plan"]
