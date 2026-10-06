from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, replace
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .compiler import CompileResult, PreparationTrace

from .config import PauseConfig, PlannerConfig, parse_duration
from .directives import resolve_directives
from .exceptions import ConfigurationError, PlanningError, PlanRenderabilityError
from .language import LanguageRun, build_language_runs, language_lookup_key, spans_from_annotations
from .linguistics import LinguisticResourcePool, RunAnalysis, analyze_run_analyses
from .model import (
    AnnotationSpan,
    BoundaryEvent,
    Diagnostic,
    LinguisticRun,
    Marker,
    PlanSegment,
    PlanSource,
    PlanTexts,
    SemanticBoundary,
    UtterancePlan,
)
from .parsers import (
    PlainDocumentParser,
    SSMDDocumentParser,
    effective_sequence_fallback_mode,
)
from .pauses import boundary_is_active, resolve_pauses
from .preparation import IdentityTextPreparer, SourceToSpokenMap, SpokenformTextPreparer
from .progress import PlannerProgressEvent, ProgressCallback, _notify_progress
from .renderability import RenderabilityIssue, contains_speech_content, preflight_segments
from .units import make_units


class UtterancePlanner:
    """Reusable planner for sequential requests.

    Linguistic resource caches are shared, but request configuration and all
    intermediate state are local to :meth:`plan`. Concurrent use is not
    promised; callers should use one planner per thread or synchronize access.
    """

    def __init__(self, config: PlannerConfig) -> None:
        self.config = config
        self._resources = LinguisticResourcePool()

    def compile(
        self,
        text: str,
        *,
        config: PlannerConfig | None = None,
        unit: str | None = None,
        trace: bool = False,
        on_progress: ProgressCallback | None = None,
    ) -> CompileResult:
        """Compile one document, optionally reporting synchronous progress.

        Progress callbacks are operational only, should be lightweight, and may raise
        exceptions that propagate to the caller.
        """
        if not isinstance(trace, bool):
            raise TypeError("trace must be a boolean")
        from .compiler import CompileResult

        plan, preparation_trace = self._plan(
            text, config=config, unit=unit, trace=trace, on_progress=on_progress
        )
        return CompileResult(plan=plan, diagnostics=plan.diagnostics, trace=preparation_trace)

    def plan(
        self,
        text: str,
        *,
        config: PlannerConfig | None = None,
        unit: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> UtterancePlan:
        """Return the semantic plan, optionally reporting synchronous progress.

        The callback is operational only and cannot affect the plan. Keep handlers
        lightweight; callback exceptions propagate to the caller.
        """
        return self.compile(text, config=config, unit=unit, on_progress=on_progress).plan

    def _plan(
        self,
        text: str,
        *,
        config: PlannerConfig | None = None,
        unit: str | None = None,
        trace: bool = False,
        on_progress: ProgressCallback | None = None,
    ) -> tuple[UtterancePlan, PreparationTrace | None]:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        effective_config = config if config is not None else self.config
        if unit is not None:
            if unit not in {"paragraph", "sentence"}:
                raise ConfigurationError("unit must be 'paragraph' or 'sentence'")
            selected_unit = unit
        else:
            selected_unit = effective_config.unit
        config = effective_config
        _notify_progress(on_progress, PlannerProgressEvent(kind="phase.started", phase="parse"))
        parsed = self._parse(text, config)
        _notify_progress(on_progress, PlannerProgressEvent(kind="phase.completed", phase="parse"))
        pause_config = _effective_pause_config(config, parsed.header)
        fallback_mode = effective_sequence_fallback_mode(parsed.header)
        document_language = parsed.document_language or config.language
        preserve_language_tags = config.document_format == "ssmd"
        identity_mode = config.text_preparation == "identity"
        skipped_details = (
            {"skipped": True, "reason": "identity preparation does not consume source analyses"}
            if identity_mode
            else {}
        )
        _notify_progress(
            on_progress,
            PlannerProgressEvent(
                kind="phase.started",
                phase="source_analysis",
                pass_index=1,
                pass_total=2,
                details=skipped_details,
            ),
        )
        source_runs = build_language_runs(
            parsed.structural_text,
            spans_from_annotations(parsed.annotations),
            document_language,
            dict(config.language_aliases),
            preserve_tags=preserve_language_tags,
        )
        if identity_mode:
            pass_a: tuple[RunAnalysis, ...] = ()
        else:
            pass_a = analyze_run_analyses(
                parsed.structural_text,
                source_runs,
                config.linguistics,
                self._resources,
                phase="source_analysis",
                pass_index=1,
                pass_total=2,
                on_progress=on_progress,
            )
        _notify_progress(
            on_progress,
            PlannerProgressEvent(
                kind="phase.completed",
                phase="source_analysis",
                pass_index=1,
                pass_total=2,
                details=skipped_details,
            ),
        )
        _notify_progress(
            on_progress,
            PlannerProgressEvent(kind="phase.started", phase="preparation"),
        )
        preparer = (
            IdentityTextPreparer()
            if config.text_preparation == "identity"
            else SpokenformTextPreparer(sequence_fallback_mode=fallback_mode)
        )
        prepared = preparer.prepare(
            parsed.structural_text,
            document_language,
            source_runs,
            parsed.annotations,
            parsed.boundaries,
            analyses=pass_a,
        )
        _notify_progress(
            on_progress,
            PlannerProgressEvent(kind="phase.completed", phase="preparation"),
        )
        spoken = prepared.spoken_text
        runs = build_language_runs(
            spoken,
            spans_from_annotations(prepared.annotations),
            document_language,
            dict(config.language_aliases),
            preserve_tags=preserve_language_tags,
        )
        if identity_mode:
            _notify_progress(
                on_progress,
                PlannerProgressEvent(
                    kind="phase.started",
                    phase="spoken_analysis",
                    pass_index=2,
                    pass_total=2,
                ),
            )
            pass_b = analyze_run_analyses(
                spoken,
                runs,
                config.linguistics,
                self._resources,
                phase="spoken_analysis",
                pass_index=2,
                pass_total=2,
                on_progress=on_progress,
            )
            pass_a = pass_b
            _notify_progress(
                on_progress,
                PlannerProgressEvent(
                    kind="phase.completed",
                    phase="spoken_analysis",
                    pass_index=2,
                    pass_total=2,
                ),
            )
        elif _same_linguistic_input(parsed.structural_text, source_runs, spoken, runs):
            reused_details: dict[str, object] = {"reused": True}
            _notify_progress(
                on_progress,
                PlannerProgressEvent(
                    kind="phase.started",
                    phase="spoken_analysis",
                    message="Reusing source linguistic analysis",
                    pass_index=2,
                    pass_total=2,
                    details=reused_details,
                ),
            )
            pass_b = pass_a
            _notify_progress(
                on_progress,
                PlannerProgressEvent(
                    kind="phase.completed",
                    phase="spoken_analysis",
                    pass_index=2,
                    pass_total=2,
                    details=reused_details,
                ),
            )
        else:
            _notify_progress(
                on_progress,
                PlannerProgressEvent(
                    kind="phase.started",
                    phase="spoken_analysis",
                    pass_index=2,
                    pass_total=2,
                ),
            )
            pass_b = analyze_run_analyses(
                spoken,
                runs,
                config.linguistics,
                self._resources,
                phase="spoken_analysis",
                pass_index=2,
                pass_total=2,
                on_progress=on_progress,
            )
            _notify_progress(
                on_progress,
                PlannerProgressEvent(
                    kind="phase.completed",
                    phase="spoken_analysis",
                    pass_index=2,
                    pass_total=2,
                ),
            )
        _notify_progress(
            on_progress,
            PlannerProgressEvent(kind="phase.started", phase="segmentation"),
        )
        tokens = tuple(token for analysis in pass_b for token in analysis.tokens)
        linguistic_runs = _linguistic_runs(runs, pass_b)
        semantic_boundaries, _ = _canonicalize_semantic_boundaries(
            _detect_linguistic_semantic_boundaries(spoken, runs, pass_b)
        )
        boundaries = list(prepared.boundaries)
        boundaries.extend(_semantic_pause_events(semantic_boundaries, start_id=len(boundaries)))
        segments = _segment(
            spoken, runs, prepared.annotations, boundaries, pause_config, document_language
        )
        segments = _attach_structural_ranges(
            segments, prepared.source_map, len(parsed.structural_text)
        )
        segments = _attach_membership(segments, tokens, prepared.annotations)
        segments = [
            resolve_directives(
                segment,
                prepared.annotations,
                voice_defaults=parsed.metadata.get("voice_defaults"),
            )
            for segment in segments
        ]
        initial_renderability = preflight_segments(segments, tokens, parsed=parsed)
        renderability_repairs: tuple[RenderabilityIssue, ...] = ()
        checked_segment_count = initial_renderability.checked_segments
        if initial_renderability.issues:
            if config.renderability_mode == "strict":
                raise PlanRenderabilityError(initial_renderability.issues, mode="strict")
            if any(
                issue.code != "renderability.punctuation_only"
                for issue in initial_renderability.issues
            ):
                raise PlanRenderabilityError(initial_renderability.issues, mode="repair")
            segments, renderability_repairs = _repair_renderer_segments(
                segments,
                initial_renderability.issues,
                spoken,
                boundaries,
                pause_config,
                prepared.annotations,
            )
            segments = [
                replace(segment, id=f"seg-{index:06d}") for index, segment in enumerate(segments)
            ]
            segments = _attach_structural_ranges(
                segments, prepared.source_map, len(parsed.structural_text)
            )
            segments = _attach_membership(segments, tokens, prepared.annotations)
            segments = [
                resolve_directives(
                    segment,
                    prepared.annotations,
                    voice_defaults=parsed.metadata.get("voice_defaults"),
                )
                for segment in segments
            ]
            post_repair = preflight_segments(segments, tokens, parsed=parsed)
            if post_repair.issues:
                raise PlanRenderabilityError(post_repair.issues, mode="repair")
        renderability_checked_segments = checked_segment_count
        boundaries.extend(_derived_boundaries(segments, boundaries, pause_config))
        semantic_boundaries = _derive_semantic_topology(segments, semantic_boundaries)
        semantic_boundaries, semantic_id_map = _canonicalize_semantic_boundaries(
            semantic_boundaries
        )
        boundaries = _relink_semantic_pause_events(boundaries, semantic_id_map)
        segments = resolve_pauses(segments, boundaries, pause_config)
        markers = tuple(_map_marker(marker, prepared.source_map) for marker in parsed.markers)
        segment_tuple = tuple(segments)
        units = make_units(
            segment_tuple,
            markers,
            tokens,
            selected_unit,
            tuple(semantic_boundaries),
        )
        _notify_progress(
            on_progress,
            PlannerProgressEvent(kind="phase.completed", phase="segmentation"),
        )
        _notify_progress(
            on_progress,
            PlannerProgressEvent(kind="phase.started", phase="finalization"),
        )
        metadata = dict(parsed.metadata)
        metadata["planning"] = {
            "linguistic_passes": 2,
            "engine_independent": True,
            "pass_a_tokens": sum(len(run.tokens) for run in pass_a),
            "renderability": {
                "mode": config.renderability_mode,
                "checked_segments": renderability_checked_segments,
                "repair_count": len(renderability_repairs),
                "guaranteed": True,
            },
        }
        diagnostics = list(parsed.diagnostics)
        diagnostics.extend(
            _renderability_repair_diagnostic(issue) for issue in renderability_repairs
        )
        if config.diagnostics:
            diagnostics.append(
                Diagnostic(
                    "planning.complete", "Plan compiled without renderer or audio processing"
                )
            )
        plan_config = _config_dict(config)
        plan_config["unit"] = selected_unit
        plan = UtterancePlan(
            source=PlanSource(parsed.source_text and config.document_format or "plain", text),
            config=plan_config,
            texts=PlanTexts(parsed.structural_text, spoken),
            preparation=prepared.info,
            languages=runs,
            annotations=prepared.annotations,
            linguistic_runs=linguistic_runs,
            semantic_boundaries=tuple(semantic_boundaries),
            boundaries=tuple(boundaries),
            tokens=tokens,
            segments=segment_tuple,
            units=units,
            markers=markers,
            document_metadata=metadata,
            warnings=tuple(parsed.warnings) + prepared.info.warnings,
            diagnostics=tuple(diagnostics),
        ).with_identity()
        plan.validate()
        preparation_trace = (
            _make_preparation_trace(parsed, prepared, plan, document_language, fallback_mode)
            if trace
            else None
        )
        _notify_progress(
            on_progress,
            PlannerProgressEvent(kind="phase.completed", phase="finalization"),
        )
        return plan, preparation_trace

    def _parse(self, text: str, config: PlannerConfig) -> Any:
        if config.document_format == "plain":
            return PlainDocumentParser().parse(text, config)
        if config.document_format == "ssmd":
            return SSMDDocumentParser().parse(text, config)
        raise PlanningError(f"unsupported document format {config.document_format!r}")

    def close(self) -> None:
        self._resources.clear()


def _same_linguistic_input(
    source_text: str,
    source_runs: tuple[LanguageRun, ...],
    spoken_text: str,
    spoken_runs: tuple[LanguageRun, ...],
) -> bool:
    """Return whether source and spoken text have identical linguistic inputs."""
    if source_text != spoken_text:
        return False
    source_shape = tuple((run.language, run.spoken_start, run.spoken_end) for run in source_runs)
    spoken_shape = tuple((run.language, run.spoken_start, run.spoken_end) for run in spoken_runs)
    return source_shape == spoken_shape


def _make_preparation_trace(
    parsed: Any,
    prepared: Any,
    plan: UtterancePlan,
    document_language: str,
    fallback_mode: Literal["spell", "preserve"],
) -> PreparationTrace:
    from .compiler import PreparationChange, PreparationTrace, PreparationTraceUnit

    changes = tuple(
        PreparationChange(
            source_start=item.get("source_start"),
            source_end=item.get("source_end"),
            output_start=item.get("output_start"),
            output_end=item.get("output_end"),
            source=item.get("source"),
            replacement=item.get("replacement"),
            kind=item.get("kind"),
            rule=item.get("rule"),
            language=item.get("language"),
        )
        for item in prepared.info.replacements
    )
    segments_by_id = {segment.id: segment for segment in plan.segments}
    trace_units: list[PreparationTraceUnit] = []
    for unit in plan.units:
        source_start, source_end = prepared.source_map.map_output_span(
            unit.spoken_start, unit.spoken_end
        )
        source_start = max(0, min(len(parsed.structural_text), source_start))
        source_end = max(source_start, min(len(parsed.structural_text), source_end))
        unit_changes = tuple(
            change
            for change in changes
            if change.source_start is not None
            and change.source_end is not None
            and (
                change.source_start < source_end
                and change.source_end > source_start
                or source_start == source_end == change.source_start
            )
        )
        languages = tuple(
            dict.fromkeys(
                segments_by_id[segment_id].language
                for segment_id in unit.segment_ids
                if segment_id in segments_by_id
            )
        )
        trace_units.append(
            PreparationTraceUnit(
                source_start=source_start,
                source_end=source_end,
                source_text=parsed.structural_text[source_start:source_end],
                prepared_text=plan.texts.spoken[unit.spoken_start : unit.spoken_end],
                effective_language=languages[0] if len(languages) == 1 else None,
                effective_languages=languages,
                transformations=unit_changes,
                split_reason=f"{unit.kind} segmentation",
                warnings=tuple(parsed.warnings) + prepared.info.warnings,
            )
        )
    return PreparationTrace(
        document_language=document_language,
        sequence_fallback_mode=fallback_mode,
        diagnostics=plan.diagnostics,
        units=tuple(trace_units),
    )


def _effective_pause_config(config: PlannerConfig, header: dict[str, Any]) -> PauseConfig:
    values: dict[str, Any] = {"mode": config.pauses.mode}
    values.update(
        {
            name: getattr(config.pauses, name)
            for name in (
                "weak",
                "clause",
                "sentence",
                "paragraph",
                "parenthetical",
                "voice_change",
                "enabled",
            )
        }
    )
    header_defaults = header.get("pause_defaults") if isinstance(header, dict) else None
    if isinstance(header_defaults, dict):
        for name, value in header_defaults.items():
            if name == "enabled" and isinstance(value, bool):
                values[name] = value
            elif name != "enabled":
                try:
                    values[name] = parse_duration(value, field_name=f"pause_defaults.{name}")
                except ConfigurationError:
                    continue
    if config.ssmd.pause_overrides:
        for name, value in config.ssmd.pause_overrides.items():
            values[name] = (
                bool(value)
                if name == "enabled"
                else parse_duration(value, field_name=f"ssmd.pause_overrides.{name}")
            )
    return PauseConfig(**values)


def _config_dict(config: PlannerConfig) -> dict[str, Any]:
    result = asdict(config)
    result["language_aliases"] = dict(config.language_aliases)
    if result.get("ssmd", {}).get("pause_overrides") is not None:
        result["ssmd"]["pause_overrides"] = dict(config.ssmd.pause_overrides or {})
    return result


def _linguistic_runs(runs: tuple[Any, ...], analyses: tuple[Any, ...]) -> tuple[LinguisticRun, ...]:
    token_start = 0
    result: list[LinguisticRun] = []
    for run, analysis in zip(runs, analyses, strict=True):
        token_end = token_start + len(analysis.tokens)
        result.append(
            LinguisticRun(
                language_run_id=run.id,
                provider=analysis.provider,
                token_start=token_start,
                token_end=token_end,
                model=analysis.model_name,
                provider_version=analysis.provider_version,
                model_version=analysis.model_version,
            )
        )
        token_start = token_end
    return tuple(result)


def _segment(
    text: str,
    runs: tuple[LanguageRun, ...],
    annotations: tuple[AnnotationSpan, ...],
    boundaries: list[BoundaryEvent],
    pause_config: PauseConfig,
    default_language: str,
) -> list[PlanSegment]:
    base_segments = _segment_text(text, runs, annotations, boundaries, pause_config)
    _validate_audio_topology(annotations, runs, base_segments)
    return _apply_atomic_audio_segments(text, base_segments, runs, annotations, default_language)


def _segment_text(
    text: str,
    runs: tuple[Any, ...],
    annotations: tuple[AnnotationSpan, ...],
    boundaries: list[BoundaryEvent],
    pause_config: PauseConfig,
) -> list[PlanSegment]:
    if not text:
        return []
    result: list[PlanSegment] = []
    for run in runs:
        local_text = text[run.spoken_start : run.spoken_end]
        for item in _split_run(local_text, run.language):
            local_start = int(getattr(item, "char_start", 0))
            local_end = int(getattr(item, "char_end", len(local_text)))
            start = run.spoken_start + local_start
            end = run.spoken_start + local_end
            if end <= start or not text[start:end].strip():
                continue
            paragraph = int(getattr(item, "paragraph_idx", 0) or 0)
            sentence = int(getattr(item, "sentence_idx", 0) or 0)
            clause = int(getattr(item, "clause_idx", 0) or 0)
            hard_cuts = {start, end}
            hard_cuts.update(
                boundary.position
                for boundary in boundaries
                if start < boundary.position < end and boundary_is_active(boundary, pause_config)
            )
            hard_cuts.update(
                point
                for annotation in _audio_annotations(annotations)
                for point in (annotation.spoken_start, annotation.spoken_end)
                if point is not None and start < point < end
            )
            semantic_cuts = {
                point
                for annotation in annotations
                for point in (annotation.spoken_start, annotation.spoken_end)
                if point is not None and start < point < end and _semantic_annotation(annotation)
            }
            ordered = _normalize_semantic_cuts(
                text,
                hard_cuts=hard_cuts,
                semantic_cuts=semantic_cuts,
            )
            clause_breaks = {
                boundary.position
                for boundary in boundaries
                if start < boundary.position < end and boundary_is_active(boundary, pause_config)
            }
            clause_breaks.update(
                annotation.spoken_end
                for annotation in annotations
                if (
                    annotation.spoken_end is not None
                    and start < annotation.spoken_end < end
                    and _semantic_annotation(annotation)
                    and not _language_annotation(annotation)
                )
            )
            current_clause = clause
            for part_start, part_end in zip(ordered, ordered[1:], strict=False):
                if part_end <= part_start or not text[part_start:part_end].strip():
                    continue
                result.append(
                    PlanSegment(
                        id=f"seg-{len(result):06d}",
                        text=text[part_start:part_end],
                        spoken_start=part_start,
                        spoken_end=part_end,
                        language=run.language,
                        paragraph=paragraph,
                        sentence=sentence,
                        clause=current_clause,
                        structural_start=None,
                        structural_end=None,
                    )
                )
                if part_end in clause_breaks:
                    current_clause += 1
    return _coalesce_neutral_punctuation_segments(
        text,
        result,
        boundaries=boundaries,
        pause_config=pause_config,
        annotations=annotations,
    )


def _is_neutral_punctuation_text(value: str) -> bool:
    significant = [character for character in value if not character.isspace()]
    return bool(significant) and all(
        unicodedata.category(character).startswith("P") for character in significant
    )


def _normalize_semantic_cuts(
    text: str,
    *,
    hard_cuts: set[int],
    semantic_cuts: set[int],
) -> list[int]:
    cuts = hard_cuts | semantic_cuts
    while True:
        ordered = sorted(cuts)
        changed = False
        for left, right in zip(ordered, ordered[1:], strict=False):
            if not _is_neutral_punctuation_text(text[left:right]):
                continue
            if left in semantic_cuts and left not in hard_cuts:
                cuts.remove(left)
                changed = True
                break
            if right in semantic_cuts and right not in hard_cuts:
                cuts.remove(right)
                changed = True
                break
        if not changed:
            return sorted(cuts)


def _coalesce_neutral_punctuation_segments(
    text: str,
    segments: list[PlanSegment],
    *,
    boundaries: list[BoundaryEvent],
    pause_config: PauseConfig,
    annotations: tuple[AnnotationSpan, ...],
) -> list[PlanSegment]:
    active_pause_positions = {
        boundary.position for boundary in boundaries if boundary_is_active(boundary, pause_config)
    }
    audio_spans = tuple(
        (annotation.spoken_start, annotation.spoken_end)
        for annotation in _audio_annotations(annotations)
        if annotation.spoken_start is not None
        and annotation.spoken_end is not None
        and annotation.spoken_start < annotation.spoken_end
    )
    audio_points = {
        annotation.spoken_start
        for annotation in _audio_annotations(annotations)
        if annotation.spoken_start is not None and annotation.spoken_end == annotation.spoken_start
    }
    semantic_positions = {
        position
        for annotation in annotations
        if _semantic_annotation(annotation)
        and not _language_annotation(annotation)
        and not _audio_annotation(annotation)
        for position in (annotation.spoken_start, annotation.spoken_end)
        if position is not None
    }

    def expansion_allowed(start: int, end: int) -> bool:
        if any(start < position < end for position in active_pause_positions | audio_points):
            return False
        return not any(
            audio_start < end and audio_end > start for audio_start, audio_end in audio_spans
        )

    def semantic_expansion_allowed(start: int, end: int) -> bool:
        return expansion_allowed(start, end) and not any(
            start < position < end for position in semantic_positions
        )

    result = list(segments)
    index = 0
    while index < len(result):
        punctuation = result[index]
        if not _is_neutral_punctuation_text(punctuation.text):
            index += 1
            continue

        previous = result[index - 1] if index else None
        following = result[index + 1] if index + 1 < len(result) else None
        if previous is not None:
            gap = text[previous.spoken_end : punctuation.spoken_start]
            expanded_start, expanded_end = previous.spoken_start, punctuation.spoken_end
            if following is not None and following.spoken_start == punctuation.spoken_end:
                whitespace_end = following.spoken_start
                while whitespace_end < following.spoken_end and text[whitespace_end].isspace():
                    whitespace_end += 1
                if whitespace_end > following.spoken_start and semantic_expansion_allowed(
                    expanded_start, whitespace_end
                ):
                    expanded_end = whitespace_end
            if (
                not _is_neutral_punctuation_text(previous.text)
                and previous.language == punctuation.language
                and not gap.strip()
                and previous.paragraph == punctuation.paragraph
                and semantic_expansion_allowed(expanded_start, expanded_end)
            ):
                result[index - 1] = replace(
                    previous,
                    text=text[expanded_start:expanded_end],
                    spoken_end=expanded_end,
                )
                if following is not None and expanded_end > punctuation.spoken_end:
                    result[index + 1] = replace(
                        following,
                        text=text[expanded_end : following.spoken_end],
                        spoken_start=expanded_end,
                    )
                del result[index]
                index = max(0, index - 1)
                continue

        if following is not None:
            gap = text[punctuation.spoken_end : following.spoken_start]
            expanded_start, expanded_end = punctuation.spoken_start, following.spoken_end
            if (
                not _is_neutral_punctuation_text(following.text)
                and following.language == punctuation.language
                and not gap.strip()
                and following.paragraph == punctuation.paragraph
                and semantic_expansion_allowed(expanded_start, expanded_end)
            ):
                result[index + 1] = replace(
                    following,
                    text=text[expanded_start:expanded_end],
                    spoken_start=expanded_start,
                )
                del result[index]
                continue
        index += 1
    for index in range(len(result) - 1):
        previous, following = result[index], result[index + 1]
        if (
            previous.spoken_end != following.spoken_start
            or previous.directives.audio is not None
            or previous.language != following.language
            or previous.paragraph != following.paragraph
            or not following.text
        ):
            continue
        previous_text = previous.text.rstrip()
        if not previous_text or not unicodedata.category(previous_text[-1]).startswith("P"):
            continue
        whitespace_end = following.spoken_start
        while whitespace_end < following.spoken_end and text[whitespace_end].isspace():
            whitespace_end += 1
        if whitespace_end == following.spoken_start or not expansion_allowed(
            previous.spoken_start, whitespace_end
        ):
            continue
        result[index] = replace(
            previous,
            text=text[previous.spoken_start : whitespace_end],
            spoken_end=whitespace_end,
        )
        result[index + 1] = replace(
            following,
            text=text[whitespace_end : following.spoken_end],
            spoken_start=whitespace_end,
        )
    return result


def _audio_annotation(annotation: AnnotationSpan) -> bool:
    tag = str(annotation.attrs.get("tag") or annotation.kind).lower().replace("_", "-")
    return tag == "audio" or annotation.attrs.get("src") is not None


def _audio_annotations(
    annotations: tuple[AnnotationSpan, ...],
) -> tuple[AnnotationSpan, ...]:
    mapped = [
        annotation
        for annotation in annotations
        if _audio_annotation(annotation)
        and annotation.spoken_start is not None
        and annotation.spoken_end is not None
    ]
    return tuple(
        sorted(
            mapped,
            key=lambda annotation: (
                annotation.spoken_start or 0,
                annotation.spoken_end or 0,
                annotation.id,
            ),
        )
    )


def _validate_audio_topology(
    annotations: tuple[AnnotationSpan, ...],
    runs: tuple[LanguageRun, ...],
    segments: list[PlanSegment],
) -> None:
    audio_annotations = _audio_annotations(annotations)
    positive = tuple(
        annotation
        for annotation in audio_annotations
        if annotation.spoken_start is not None
        and annotation.spoken_end is not None
        and annotation.spoken_start < annotation.spoken_end
    )
    points = tuple(
        annotation
        for annotation in audio_annotations
        if annotation.spoken_start is not None
        and annotation.spoken_end is not None
        and annotation.spoken_start == annotation.spoken_end
    )

    for previous, current in zip(positive, positive[1:], strict=False):
        previous_end = previous.spoken_end
        current_start = current.spoken_start
        if previous_end is not None and current_start is not None and current_start < previous_end:
            raise PlanningError(
                "Overlapping audio annotations are not supported by UtterPlan schema-v3 segment semantics"
            )

    point_position: int | None = None
    for point in points:
        position = point.spoken_start
        if position is None:
            continue
        if position == point_position:
            raise PlanningError(
                "Multiple zero-width audio annotations at the same spoken position are not supported"
            )
        point_position = position

    positive_index = 0
    for point in points:
        position = point.spoken_start
        if position is None:
            continue
        while positive_index < len(positive):
            positive_end = positive[positive_index].spoken_end
            if positive_end is None or positive_end > position:
                break
            positive_index += 1
        if positive_index == len(positive):
            break
        candidate = positive[positive_index]
        start, end = candidate.spoken_start, candidate.spoken_end
        if start is not None and end is not None and start < position < end:
            raise PlanningError(
                "A zero-width audio occurrence inside another audio fallback is not supported"
            )

    for audio in positive:
        start, end = audio.spoken_start, audio.spoken_end
        if start is None or end is None:
            continue
        languages = {
            language_lookup_key(run.language)
            for run in runs
            if run.spoken_start < end and run.spoken_end > start
        }
        if len(languages) > 1:
            raise PlanningError(
                "Audio fallback spans multiple effective languages and cannot be represented as one atomic media segment"
            )

        paragraphs = {
            segment.paragraph
            for segment in segments
            if segment.spoken_start < end and segment.spoken_end > start
        }
        if len(paragraphs) > 1:
            raise PlanningError(
                "Audio fallback spans multiple paragraphs and cannot be represented as one atomic media segment"
            )

        for annotation in annotations:
            if (
                annotation.id == audio.id
                or _audio_annotation(annotation)
                or not _semantic_annotation(annotation)
                or annotation.spoken_start is None
                or annotation.spoken_end is None
            ):
                continue
            if start < annotation.spoken_start and annotation.spoken_end < end:
                raise PlanningError(
                    "Renderer-affecting annotations nested inside an audio fallback are not supported"
                )


def _apply_atomic_audio_segments(
    text: str,
    segments: list[PlanSegment],
    runs: tuple[LanguageRun, ...],
    annotations: tuple[AnnotationSpan, ...],
    default_language: str,
) -> list[PlanSegment]:
    positive = tuple(
        annotation
        for annotation in _audio_annotations(annotations)
        if annotation.spoken_start is not None
        and annotation.spoken_end is not None
        and annotation.spoken_start < annotation.spoken_end
    )
    consumed_ids: set[str] = set()
    media_segments: list[PlanSegment] = []

    for annotation in positive:
        start, end = annotation.spoken_start, annotation.spoken_end
        if start is None or end is None:
            continue
        intersecting = [
            segment
            for segment in segments
            if segment.spoken_start < end and segment.spoken_end > start
        ]
        for segment in intersecting:
            if segment.spoken_start < start or segment.spoken_end > end:
                raise PlanningError(
                    "Audio fallback boundaries do not align with base PlanSegment boundaries"
                )

        if (
            len(intersecting) == 1
            and intersecting[0].spoken_start == start
            and intersecting[0].spoken_end == end
        ):
            continue

        language, paragraph, sentence, clause = _media_context(
            start, end, segments, runs, default_language
        )
        media_segments.append(
            PlanSegment(
                id="",
                text=text[start:end],
                spoken_start=start,
                spoken_end=end,
                language=language,
                paragraph=paragraph,
                sentence=sentence,
                clause=clause,
            )
        )
        consumed_ids.update(segment.id for segment in intersecting)

    points = tuple(
        annotation
        for annotation in _audio_annotations(annotations)
        if annotation.spoken_start is not None
        and annotation.spoken_end is not None
        and annotation.spoken_start == annotation.spoken_end
    )
    for annotation in points:
        position = annotation.spoken_start
        if position is None:
            continue
        language, paragraph, sentence, clause = _media_context(
            position, position, segments, runs, default_language
        )
        media_segments.append(
            PlanSegment(
                id="",
                text="",
                spoken_start=position,
                spoken_end=position,
                language=language,
                paragraph=paragraph,
                sentence=sentence,
                clause=clause,
                annotation_ids=(annotation.id,),
            )
        )

    kept = [segment for segment in segments if segment.id not in consumed_ids]
    ordered = sorted(
        enumerate(kept + media_segments),
        key=lambda item: (
            item[1].spoken_start,
            0 if item[1].spoken_start == item[1].spoken_end else 1,
            item[0],
        ),
    )
    return [
        replace(segment, id=f"seg-{index:06d}")
        for index, (_original_order, segment) in enumerate(ordered)
    ]


def _media_context(
    start: int,
    end: int,
    segments: list[PlanSegment],
    runs: tuple[LanguageRun, ...],
    default_language: str,
) -> tuple[str, int, int, int]:
    covered = [
        segment
        for segment in segments
        if start <= segment.spoken_start
        and segment.spoken_end <= end
        and segment.spoken_start < end
        and segment.spoken_end > start
    ]
    if covered:
        context = covered[0]
        return context.language, context.paragraph, context.sentence, context.clause

    preceding = [segment for segment in segments if segment.spoken_end <= start]
    if preceding:
        context = max(preceding, key=lambda segment: (segment.spoken_end, segment.spoken_start))
        return context.language, context.paragraph, context.sentence, context.clause

    following = [segment for segment in segments if segment.spoken_start >= end]
    if following:
        context = min(following, key=lambda segment: (segment.spoken_start, segment.spoken_end))
        return context.language, context.paragraph, context.sentence, context.clause

    preceding_runs = [run for run in runs if run.spoken_end <= start]
    if preceding_runs:
        return max(preceding_runs, key=lambda run: run.spoken_end).language, 0, 0, 0

    following_runs = [run for run in runs if run.spoken_start >= end]
    if following_runs:
        return min(following_runs, key=lambda run: run.spoken_start).language, 0, 0, 0

    overlapping_runs = [run for run in runs if run.spoken_start < end and run.spoken_end > start]
    if overlapping_runs:
        return overlapping_runs[0].language, 0, 0, 0
    return default_language, 0, 0, 0


def _split_run(text: str, language: str) -> list[Any]:
    try:
        import phrasplit

        # Sentence topology stays on the deterministic phrasplit path.
        items = phrasplit.split_with_offsets(
            text, mode="sentence", use_spacy=False, language=language_lookup_key(language)
        )
    except ImportError:
        return [_FallbackSplit(0, len(text), 0, 0)] if text else []
    except TypeError as exc:
        raise PlanningError("sentence segmentation integration failed") from exc
    except (OSError, ValueError):
        return [_FallbackSplit(0, len(text), 0, 0)] if text else []
    valid: list[Any] = []
    previous = 0
    for item in items:
        start = int(getattr(item, "char_start", -1))
        end = int(getattr(item, "char_end", -1))
        if (
            0 <= start < end <= len(text)
            and text[start:end] == str(getattr(item, "text", text[start:end]))
            and start >= previous
        ):
            valid.append(item)
            previous = end
    if not valid and text:
        return [_FallbackSplit(0, len(text), 0, 0, text)]
    if any(
        text[left.char_end : right.char_start].strip()
        for left, right in zip(valid, valid[1:], strict=False)
    ):
        return [_FallbackSplit(0, len(text), 0, 0, text)]
    return _repair_quote_boundaries(_split_closing_quote_boundaries(valid, text), text)


def _split_closing_quote_boundaries(items: list[Any], text: str) -> list[Any]:
    pattern = re.compile(r'[.!?]["\'»”’]+\s+(?=[A-ZÄÖÜÀ-Þ])')
    repaired: list[Any] = []
    for item in items:
        start = int(item.char_start)
        sentence = int(getattr(item, "sentence_idx", 0) or 0)
        paragraph = int(getattr(item, "paragraph_idx", 0) or 0)
        for match in pattern.finditer(text[start : int(item.char_end)]):
            end = start + match.start() + len(match.group(0).rstrip())
            if end <= start or end >= int(item.char_end):
                continue
            repaired.append(
                _FallbackSplit(
                    start,
                    end,
                    paragraph,
                    sentence,
                    text[start:end],
                )
            )
            sentence += 1
            start += match.end()
        if start < int(item.char_end):
            repaired.append(
                _FallbackSplit(
                    start,
                    int(item.char_end),
                    paragraph,
                    sentence,
                    text[start : int(item.char_end)],
                )
            )
    return repaired


def _repair_quote_boundaries(items: list[Any], text: str) -> list[Any]:
    repaired: list[Any] = []
    closing = "\"'”’)]}"
    for item in items:
        current = _FallbackSplit(
            int(item.char_start),
            int(item.char_end),
            int(getattr(item, "paragraph_idx", 0) or 0),
            int(getattr(item, "sentence_idx", 0) or 0),
            text[int(item.char_start) : int(item.char_end)],
        )
        if (
            repaired
            and repaired[-1].text.rstrip().endswith((".", "!", "?"))
            and current.text.lstrip().startswith(tuple(closing))
        ):
            previous = repaired[-1]
            previous.char_end = current.char_end
            previous.text = text[previous.char_start : previous.char_end]
        else:
            repaired.append(current)
    return repaired


class _FallbackSplit:
    def __init__(
        self, char_start: int, char_end: int, paragraph_idx: int, sentence_idx: int, text: str = ""
    ) -> None:
        self.char_start = char_start
        self.char_end = char_end
        self.paragraph_idx = paragraph_idx
        self.sentence_idx = sentence_idx
        self.clause_idx = 0
        self.text = text


def _detect_linguistic_semantic_boundaries(
    text: str,
    runs: tuple[Any, ...],
    analyses: tuple[RunAnalysis, ...],
) -> list[SemanticBoundary]:
    try:
        import phrasplit
    except ImportError:
        return []
    result: list[SemanticBoundary] = []
    for run, analysis in zip(runs, analyses, strict=True):
        local = text[run.spoken_start : run.spoken_end]
        clause_items = []
        if analysis.provider_doc is not None:
            try:
                clause_items = phrasplit.detect_clause_boundaries(
                    local,
                    language=language_lookup_key(run.language),
                    doc=analysis.provider_doc,
                )
            except (OSError, TypeError, ValueError):
                clause_items = []
        for item in clause_items:
            kind = str(getattr(item, "kind", ""))
            try:
                start = int(getattr(item, "char_start", 0))
                raw_end = int(getattr(item, "char_end", start + 1))
            except (TypeError, ValueError, OverflowError):
                continue
            if not (0 <= start <= raw_end <= len(local)):
                continue
            end = raw_end if raw_end > start else min(len(local), start + 1)
            attrs = {
                "detected_kind": kind,
                "detector_start": start,
                "detector_end": raw_end,
                "detector_run_spoken_start": run.spoken_start,
            }
            if "parenthetical" in kind:
                semantic_kind = "parenthetical"
                position = _parenthetical_semantic_position(kind, start, end)
            elif "clause" in kind or "comma" in kind:
                semantic_kind = "clause"
                position = _normalize_clause_split_position(local, start, end)
                attrs["detector_spoken_start"] = run.spoken_start + start
            else:
                continue
            if 0 < position < len(local):
                result.append(
                    SemanticBoundary(
                        "",
                        run.spoken_start + position,
                        semantic_kind,
                        origin="phrasplit",
                        language_run_id=run.id,
                        attrs=attrs,
                    )
                )
        try:
            parenthetical_items = phrasplit.detect_parenthetical_boundaries(
                local, language=language_lookup_key(run.language)
            )
        except (AttributeError, OSError, TypeError, ValueError):
            parenthetical_items = []
        for item in parenthetical_items:
            kind = str(getattr(item, "kind", "parenthetical"))
            try:
                start = int(getattr(item, "char_start", 0))
                raw_end = int(getattr(item, "char_end", start))
            except (TypeError, ValueError, OverflowError):
                continue
            if not (0 <= start <= raw_end <= len(local)):
                continue
            position = _parenthetical_semantic_position(kind, start, raw_end)
            if not 0 < position < len(local):
                continue
            result.append(
                SemanticBoundary(
                    "",
                    run.spoken_start + position,
                    "parenthetical",
                    origin="phrasplit",
                    language_run_id=run.id,
                    attrs={
                        "detected_kind": kind,
                        "detector_start": start,
                        "detector_end": raw_end,
                        "detector_run_spoken_start": run.spoken_start,
                    },
                )
            )
    return result


def _parenthetical_semantic_position(kind: str, start: int, end: int) -> int:
    if kind == "parenthetical_close":
        return end
    return start


def _normalize_clause_split_position(text: str, start: int, end: int) -> int:
    if end <= start:
        end = min(len(text), start + 1)
    position = end
    while position < len(text) and text[position] in ",;:，；：—–-":
        position += 1
    while position < len(text) and (
        text[position] in ")]}'\"»”’" or unicodedata.category(text[position]) in {"Pe", "Pf"}
    ):
        position += 1
    while position < len(text) and (
        text[position] == "\t" or unicodedata.category(text[position]) == "Zs"
    ):
        position += 1
    return position


def _canonicalize_semantic_boundaries(
    boundaries: list[SemanticBoundary] | tuple[SemanticBoundary, ...],
) -> tuple[list[SemanticBoundary], dict[str, str]]:
    grouped: dict[tuple[int, str], list[SemanticBoundary]] = {}
    for boundary in boundaries:
        grouped.setdefault((boundary.position, boundary.kind), []).append(boundary)
    canonical: list[SemanticBoundary] = []
    for position, kind in sorted(grouped):
        producers = sorted(
            grouped[(position, kind)],
            key=lambda item: (item.origin, item.language_run_id or "", item.id),
        )
        selected = producers[0]
        origins = sorted({item.origin for item in producers})
        attrs = dict(selected.attrs)
        if len(origins) > 1:
            attrs["origins"] = origins
        canonical.append(
            SemanticBoundary(
                "",
                position,
                kind,
                origin=origins[0],
                language_run_id=selected.language_run_id,
                attrs=attrs,
            )
        )
    canonical.sort(key=lambda item: (item.position, item.kind, item.origin, item.id))
    id_map: dict[str, str] = {}
    identified: list[SemanticBoundary] = []
    for index, boundary in enumerate(canonical):
        boundary_id = f"semantic-boundary-{index:06d}"
        identified.append(replace(boundary, id=boundary_id))
        for source in grouped[(boundary.position, boundary.kind)]:
            if source.id:
                id_map[source.id] = boundary_id
    return identified, id_map


def _semantic_pause_events(
    semantic_boundaries: list[SemanticBoundary], *, start_id: int
) -> list[BoundaryEvent]:
    result: list[BoundaryEvent] = []
    for boundary in semantic_boundaries:
        if boundary.origin != "phrasplit":
            continue
        detected_kind = str(boundary.attrs.get("detected_kind", ""))
        if boundary.kind == "clause":
            event_kind = "clausal_comma"
            position = int(boundary.attrs.get("detector_spoken_start", boundary.position))
            event_attrs = {
                "detected_kind": detected_kind,
                "automatic": True,
                "semantic_boundary_id": boundary.id,
            }
        elif boundary.kind == "parenthetical":
            event_kind = "parenthetical"
            position = boundary.position
            event_attrs = {
                "detected_kind": detected_kind,
                "automatic": True,
                "anchor": "before",
                "semantic_boundary_id": boundary.id,
            }
        else:
            continue
        result.append(
            BoundaryEvent(
                f"boundary-{start_id + len(result):06d}",
                position,
                event_kind,
                origin=boundary.origin,
                strength="weak",
                attrs=event_attrs,
            )
        )
    return result


def _derive_semantic_topology(
    segments: list[PlanSegment], existing: list[SemanticBoundary]
) -> list[SemanticBoundary]:
    result = list(existing)
    existing_keys = {(item.position, item.kind) for item in existing}
    for previous, current in zip(segments, segments[1:], strict=False):
        if previous.paragraph != current.paragraph:
            kind = "paragraph"
        elif previous.sentence != current.sentence:
            kind = "sentence"
        else:
            continue
        key = (previous.spoken_end, kind)
        if key in existing_keys:
            continue
        result.append(SemanticBoundary("", key[0], kind, origin="planner"))
        existing_keys.add(key)
    return result


def _relink_semantic_pause_events(
    boundaries: list[BoundaryEvent], id_map: dict[str, str]
) -> list[BoundaryEvent]:
    result: list[BoundaryEvent] = []
    for event in boundaries:
        semantic_id = event.attrs.get("semantic_boundary_id")
        if isinstance(semantic_id, str) and semantic_id in id_map:
            attrs = dict(event.attrs)
            attrs["semantic_boundary_id"] = id_map[semantic_id]
            event = replace(event, attrs=attrs)
        result.append(event)
    return result


def _derived_boundaries(
    segments: list[PlanSegment], existing: list[BoundaryEvent], config: PauseConfig
) -> list[BoundaryEvent]:
    result: list[BoundaryEvent] = []
    existing_keys = {
        (event.position, event.kind)
        for event in existing
        if event.kind in {"paragraph", "sentence"}
    }
    next_id = len(existing)
    for previous, current in zip(segments, segments[1:], strict=False):
        kind: str | None = None
        strength: str | None = None
        if previous.paragraph != current.paragraph:
            kind, strength = "paragraph", "paragraph"
        elif previous.sentence != current.sentence:
            kind, strength = "sentence", "sentence"
        elif config.mode == "auto" and _voice_changed(previous, current):
            kind, strength = "voice_change", "weak"
        if kind is not None:
            position = previous.spoken_end
            if (position, kind) in existing_keys:
                continue
            result.append(
                BoundaryEvent(
                    f"boundary-{next_id:06d}",
                    position,
                    kind,
                    origin="planner",
                    strength=strength,
                    attrs={"automatic": True},
                )
            )
            existing_keys.add((position, kind))
            next_id += 1
    return result


def _voice_changed(previous: PlanSegment, current: PlanSegment) -> bool:
    left = previous.directives.voice.reference if previous.directives.voice else None
    right = current.directives.voice.reference if current.directives.voice else None
    return left != right


def _attach_structural_ranges(
    segments: list[PlanSegment], source_map: Any, structural_length: int
) -> list[PlanSegment]:
    output: list[PlanSegment] = []
    for segment in segments:
        start, end = source_map.map_output_span(segment.spoken_start, segment.spoken_end)
        start = max(0, min(structural_length, start))
        end = max(start, min(structural_length, end))
        output.append(replace(segment, structural_start=start, structural_end=end))
    return output


def _attach_membership(
    segments: list[PlanSegment], tokens: tuple[Any, ...], annotations: tuple[AnnotationSpan, ...]
) -> list[PlanSegment]:
    output: list[PlanSegment] = []
    for segment in segments:
        token_indices = tuple(
            index
            for index, token in enumerate(tokens)
            if token.spoken_start < segment.spoken_end and token.spoken_end > segment.spoken_start
        )
        annotation_ids = (
            list(segment.annotation_ids) if segment.spoken_start == segment.spoken_end else []
        )
        for annotation in annotations:
            start = annotation.spoken_start
            end = annotation.spoken_end
            if start is None or end is None:
                continue
            if (
                start < segment.spoken_end
                and end > segment.spoken_start
                and annotation.id not in annotation_ids
            ):
                annotation_ids.append(annotation.id)
        output.append(
            replace(segment, token_indices=token_indices, annotation_ids=tuple(annotation_ids))
        )
    return output


def _repair_renderer_segments(
    segments: list[PlanSegment],
    issues: tuple[RenderabilityIssue, ...],
    text: str,
    boundaries: list[BoundaryEvent],
    pause_config: PauseConfig,
    annotations: tuple[AnnotationSpan, ...],
) -> tuple[list[PlanSegment], tuple[RenderabilityIssue, ...]]:
    current = list(segments)
    repairs: list[RenderabilityIssue] = []
    for issue in issues:
        index = next(
            (i for i, segment in enumerate(current) if segment.id == issue.segment_id), None
        )
        if index is None:
            continue
        punctuation = current[index]
        significant = [char for char in punctuation.text if not char.isspace()]
        terminal = bool(significant and significant[-1] in ".!?…。！？")
        directions = (-1, 1) if terminal else (1, -1)
        merged = False
        for direction in directions:
            neighbor_index = index + direction
            if not 0 <= neighbor_index < len(current):
                continue
            neighbor = current[neighbor_index]
            if not _can_merge_punctuation(
                punctuation,
                neighbor,
                direction,
                text,
                boundaries,
                pause_config,
                annotations,
            ):
                continue
            start = min(punctuation.spoken_start, neighbor.spoken_start)
            end = max(punctuation.spoken_end, neighbor.spoken_end)
            replacement_segment = replace(
                neighbor,
                text=text[start:end],
                spoken_start=start,
                spoken_end=end,
                structural_start=None,
                structural_end=None,
                token_indices=(),
                annotation_ids=(),
            )
            current[neighbor_index] = replacement_segment
            del current[index]
            repairs.append(replace(issue, repair="merge_neutral_punctuation"))
            merged = True
            break
        if merged:
            continue
        if not _can_drop_punctuation(punctuation, annotations):
            failed = replace(
                issue,
                code="renderability.repair_failed",
                reason="repair_failed",
                hint="The punctuation segment has semantic or media constraints that prevent safe merging or omission.",
            )
            raise PlanRenderabilityError((failed,), mode="repair")
        del current[index]
        repairs.append(replace(issue, repair="drop_non_speech_punctuation"))
    return current, tuple(repairs)


def _can_merge_punctuation(
    punctuation: PlanSegment,
    neighbor: PlanSegment,
    direction: int,
    text: str,
    boundaries: list[BoundaryEvent],
    pause_config: PauseConfig,
    annotations: tuple[AnnotationSpan, ...],
) -> bool:
    if (
        not _is_neutral_punctuation_text(punctuation.text)
        or not contains_speech_content(neighbor.text)
        or punctuation.language != neighbor.language
        or punctuation.paragraph != neighbor.paragraph
        or punctuation.directives != neighbor.directives
    ):
        return False
    if direction < 0:
        gap_start, gap_end = neighbor.spoken_end, punctuation.spoken_start
    else:
        gap_start, gap_end = punctuation.spoken_end, neighbor.spoken_start
    if gap_start > gap_end or text[gap_start:gap_end].strip():
        return False
    if any(
        gap_start <= boundary.position <= gap_end and boundary_is_active(boundary, pause_config)
        for boundary in boundaries
    ):
        return False
    if _audio_crosses_join(gap_start, gap_end, annotations):
        return False
    return not any(
        not _language_annotation(annotation)
        and _semantic_annotation(annotation)
        and any(
            position is not None and gap_start <= position <= gap_end
            for position in (annotation.spoken_start, annotation.spoken_end)
        )
        for annotation in annotations
    )


def _audio_crosses_join(
    gap_start: int, gap_end: int, annotations: tuple[AnnotationSpan, ...]
) -> bool:
    for annotation in _audio_annotations(annotations):
        start, end = annotation.spoken_start, annotation.spoken_end
        if start is None or end is None:
            continue
        if start == end:
            if gap_start <= start <= gap_end:
                return True
        elif gap_start == gap_end:
            if start < gap_start < end:
                return True
        elif start < gap_end and end > gap_start:
            return True
    return False


def _can_drop_punctuation(segment: PlanSegment, annotations: tuple[AnnotationSpan, ...]) -> bool:
    directives = segment.directives
    if any(
        value is not None
        for value in (
            directives.audio,
            directives.pronunciation,
            directives.substitution,
            directives.say_as,
        )
    ):
        return False
    protected_tags = {"audio", "phoneme", "pronunciation", "sub", "say-as"}
    for annotation in annotations:
        tag = str(annotation.attrs.get("tag") or annotation.kind).lower().replace("_", "-")
        if tag not in protected_tags:
            continue
        if annotation.id in segment.annotation_ids:
            return False
        start, end = annotation.spoken_start, annotation.spoken_end
        if start is None or end is None:
            continue
        if (start == end and segment.spoken_start <= start <= segment.spoken_end) or (
            start < segment.spoken_end and end > segment.spoken_start
        ):
            return False
    return True


def _renderability_repair_diagnostic(issue: RenderabilityIssue) -> Diagnostic:
    if issue.repair == "drop_non_speech_punctuation":
        message = f"Removed isolated punctuation-only renderer segment {issue.text!r}"
    else:
        message = f"Merged neutral punctuation into an adjacent spoken segment {issue.text!r}"
    return Diagnostic(
        code="planning.renderability.repaired",
        message=message,
        severity="warning",
        source_start=issue.source_start,
        source_end=issue.source_end,
        line=issue.line,
        column=issue.column,
        hint="Review the source if this punctuation was intended to be spoken.",
    )


def _language_annotation(annotation: AnnotationSpan) -> bool:
    return set(annotation.attrs).issubset({"lang", "language", "tag"}) and (
        "lang" in annotation.attrs or "language" in annotation.attrs
    )


def _semantic_annotation(annotation: AnnotationSpan) -> bool:
    tag = str(annotation.attrs.get("tag") or annotation.kind).lower().replace("_", "-")
    if tag in {
        "voice",
        "lang",
        "phoneme",
        "pronunciation",
        "prosody",
        "emphasis",
        "say-as",
        "sub",
        "audio",
        "extension",
        "directive",
    }:
        return True
    return any(
        key in annotation.attrs
        for key in (
            "lang",
            "language",
            "voice",
            "voice-name",
            "voice-languages",
            "gender",
            "age",
            "variant",
            "ph",
            "alphabet",
            "ipa",
            "sampa",
            "rate",
            "pitch",
            "volume",
            "emphasis",
            "as",
            "format",
            "detail",
            "sub",
            "src",
            "desc",
            "clip",
            "speed",
            "repeat",
            "repeatdur",
            "repeatDur",
            "level",
            "ext",
        )
    )


def _map_marker(marker: Marker, source_map: SourceToSpokenMap) -> Marker:
    position, _ = source_map.map_source_span(marker.spoken_position, marker.spoken_position)
    return replace(marker, spoken_position=position)
