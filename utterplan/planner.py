from __future__ import annotations

import re
from dataclasses import asdict, replace
from typing import Any

from .config import PauseConfig, PlannerConfig, parse_duration
from .directives import resolve_directives
from .exceptions import ConfigurationError, PlanningError
from .language import build_language_runs, spans_from_annotations
from .linguistics import LinguisticResourcePool, analyze_run_analyses
from .model import (
    AnnotationSpan,
    BoundaryEvent,
    Diagnostic,
    LinguisticRun,
    Marker,
    PlanSegment,
    PlanSource,
    PlanTexts,
    UtterancePlan,
)
from .parsers import PlainDocumentParser, SSMDDocumentParser
from .pauses import boundary_is_active, resolve_pauses
from .preparation import IdentityTextPreparer, SourceToSpokenMap, SpokenformTextPreparer
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

    def plan(
        self, text: str, *, config: PlannerConfig | None = None, unit: str | None = None
    ) -> UtterancePlan:
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
        parsed = self._parse(text, config)
        pause_config = _effective_pause_config(config, parsed.header)
        source_runs = build_language_runs(
            parsed.structural_text,
            spans_from_annotations(parsed.annotations),
            config.language,
            dict(config.language_aliases),
        )
        pass_a = analyze_run_analyses(
            parsed.structural_text, source_runs, config.linguistics, self._resources
        )
        preparer = (
            IdentityTextPreparer()
            if config.text_preparation == "identity"
            else SpokenformTextPreparer()
        )
        prepared = preparer.prepare(
            parsed.structural_text,
            config.language,
            source_runs,
            parsed.annotations,
            parsed.boundaries,
            analyses=pass_a,
        )
        spoken = prepared.spoken_text
        runs = build_language_runs(
            spoken,
            spans_from_annotations(prepared.annotations),
            config.language,
            dict(config.language_aliases),
        )
        pass_b = analyze_run_analyses(spoken, runs, config.linguistics, self._resources)
        tokens = tuple(token for analysis in pass_b for token in analysis.tokens)
        linguistic_runs = _linguistic_runs(runs, pass_b)
        boundaries = list(prepared.boundaries)
        boundaries.extend(_linguistic_boundaries(spoken, runs, config, start_id=len(boundaries)))
        segments = _segment(
            spoken, runs, prepared.annotations, boundaries, config, pause_config, pass_b
        )
        segments = _attach_membership(segments, tokens, prepared.annotations)
        segments = [resolve_directives(segment, prepared.annotations) for segment in segments]
        boundaries.extend(_derived_boundaries(segments, boundaries, pause_config))
        segments = resolve_pauses(segments, boundaries, pause_config)
        markers = tuple(_map_marker(marker, prepared.source_map) for marker in parsed.markers)
        segment_tuple = tuple(segments)
        units = make_units(segment_tuple, markers, tokens, selected_unit)
        metadata = dict(parsed.metadata)
        metadata["planning"] = {
            "linguistic_passes": 2,
            "engine_independent": True,
            "pass_a_tokens": sum(len(run.tokens) for run in pass_a),
        }
        diagnostics: tuple[Diagnostic, ...] = ()
        if config.diagnostics:
            diagnostics = (
                Diagnostic(
                    "planning.complete", "Plan compiled without renderer or audio processing"
                ),
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
            boundaries=tuple(boundaries),
            tokens=tokens,
            segments=segment_tuple,
            units=units,
            markers=markers,
            document_metadata=metadata,
            warnings=tuple(parsed.warnings) + prepared.info.warnings,
            diagnostics=diagnostics,
        ).with_identity()
        plan.validate()
        return plan

    def _parse(self, text: str, config: PlannerConfig) -> Any:
        if config.document_format == "plain":
            return PlainDocumentParser().parse(text, config)
        if config.document_format == "ssmd":
            return SSMDDocumentParser().parse(text, config)
        raise PlanningError(f"unsupported document format {config.document_format!r}")

    def close(self) -> None:
        self._resources.clear()


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
    if config.ssmd.pause_defaults:
        for name, value in config.ssmd.pause_defaults.items():
            values[name] = (
                bool(value)
                if name == "enabled"
                else parse_duration(value, field_name=f"ssmd.pause_defaults.{name}")
            )
    return PauseConfig(**values)


def _config_dict(config: PlannerConfig) -> dict[str, Any]:
    result = asdict(config)
    result["language_aliases"] = dict(config.language_aliases)
    if result.get("ssmd", {}).get("pause_defaults") is not None:
        result["ssmd"]["pause_defaults"] = dict(config.ssmd.pause_defaults or {})
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
    runs: tuple[Any, ...],
    annotations: tuple[AnnotationSpan, ...],
    boundaries: list[BoundaryEvent],
    config: PlannerConfig,
    pause_config: PauseConfig,
    analyses: tuple[Any, ...] = (),
) -> list[PlanSegment]:
    if not text:
        return []
    result: list[PlanSegment] = []
    for run_index, run in enumerate(runs):
        local_text = text[run.spoken_start : run.spoken_end]
        analysis = analyses[run_index] if run_index < len(analyses) else None
        for item in _split_run(local_text, run.language, config, analysis):
            local_start = int(getattr(item, "char_start", 0))
            local_end = int(getattr(item, "char_end", len(local_text)))
            start = run.spoken_start + local_start
            end = run.spoken_start + local_end
            if end <= start or not text[start:end].strip():
                continue
            paragraph = int(getattr(item, "paragraph_idx", 0) or 0)
            sentence = int(getattr(item, "sentence_idx", 0) or 0)
            clause = int(getattr(item, "clause_idx", 0) or 0)
            cuts = {start, end}
            cuts.update(
                boundary.position
                for boundary in boundaries
                if start < boundary.position < end and boundary_is_active(boundary, pause_config)
            )
            cuts.update(
                point
                for annotation in annotations
                for point in (annotation.spoken_start, annotation.spoken_end)
                if point is not None and start < point < end and _semantic_annotation(annotation)
            )
            ordered = sorted(cuts)
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
    return result


def _split_run(
    text: str, language: str, config: PlannerConfig, analysis: Any | None = None
) -> list[Any]:
    try:
        import phrasplit

        kwargs: dict[str, Any] = {"mode": "sentence", "use_spacy": False, "language": language}
        if analysis is not None and analysis.provider_doc is not None:
            kwargs["nlp"] = analysis.provider_doc
        items = phrasplit.split_with_offsets(text, **kwargs)
    except (ImportError, OSError, TypeError, ValueError):
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


def _linguistic_boundaries(
    text: str, runs: tuple[Any, ...], config: PlannerConfig, *, start_id: int = 0
) -> list[BoundaryEvent]:
    try:
        import phrasplit
    except ImportError:
        return []
    result: list[BoundaryEvent] = []
    for run in runs:
        local = text[run.spoken_start : run.spoken_end]
        try:
            clause_items = phrasplit.detect_clause_boundaries(
                local, language=run.language, use_spacy=False
            )
        except (OSError, TypeError, ValueError):
            clause_items = []
        for item in clause_items:
            kind = str(getattr(item, "kind", ""))
            event_kind = (
                "parenthetical"
                if "parenthetical" in kind
                else "clausal_comma"
                if ("clause" in kind or "comma" in kind)
                else None
            )
            if event_kind:
                result.append(
                    BoundaryEvent(
                        f"boundary-{start_id + len(result):06d}",
                        run.spoken_start + int(getattr(item, "char_start", 0)),
                        event_kind,
                        origin="phrasplit",
                        strength="weak",
                        attrs={"detected_kind": kind, "automatic": True},
                    )
                )
        try:
            parenthetical_items = phrasplit.detect_parenthetical_boundaries(
                local, language=run.language
            )
        except (AttributeError, OSError, TypeError, ValueError):
            parenthetical_items = []
        for item in parenthetical_items:
            kind = str(getattr(item, "kind", "parenthetical"))
            char_start = int(getattr(item, "char_start", 0))
            char_end = int(getattr(item, "char_end", char_start))
            if kind == "parenthetical_open":
                local_position = char_start
            elif kind == "parenthetical_close":
                local_position = char_end
            else:
                continue
            result.append(
                BoundaryEvent(
                    f"boundary-{start_id + len(result):06d}",
                    run.spoken_start + local_position,
                    "parenthetical",
                    origin="phrasplit",
                    strength="weak",
                    attrs={
                        "detected_kind": kind,
                        "automatic": True,
                        "anchor": "before",
                    },
                )
            )
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
        annotation_ids = tuple(
            annotation.id
            for annotation in annotations
            if annotation.spoken_start is not None
            and annotation.spoken_end is not None
            and annotation.spoken_start < segment.spoken_end
            and annotation.spoken_end > segment.spoken_start
        )
        output.append(replace(segment, token_indices=token_indices, annotation_ids=annotation_ids))
    return output


def _language_annotation(annotation: AnnotationSpan) -> bool:
    return set(annotation.attrs).issubset({"lang", "language", "tag"}) and (
        "lang" in annotation.attrs or "language" in annotation.attrs
    )


def _semantic_annotation(annotation: AnnotationSpan) -> bool:
    return any(
        key in annotation.attrs
        for key in (
            "lang",
            "language",
            "voice",
            "voice_name",
            "ph",
            "phonemes",
            "rate",
            "pitch",
            "volume",
            "emphasis",
            "level",
            "audio",
            "audio_src",
            "src",
            "speed",
        )
    )


def _map_marker(marker: Marker, source_map: SourceToSpokenMap) -> Marker:
    position, _ = source_map.map_source_span(marker.spoken_position, marker.spoken_position)
    return replace(marker, spoken_position=position)
