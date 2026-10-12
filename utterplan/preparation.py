from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .linguistics import RunAnalysis

from .exceptions import PlanFormatError, TextPreparationError
from .language import LanguageRun, language_lookup_key
from .model import AnnotationSpan, BoundaryEvent, TextPreparationInfo
from .parsers import ParsedDocument, normalize_ssmd_substitution_spans


class SourceToSpokenMap(Protocol):
    source_length: int
    output_length: int

    def map_source_span(self, start: int, end: int) -> tuple[int, int]: ...

    def map_output_span(self, start: int, end: int) -> tuple[int, int]: ...


@dataclass(frozen=True, slots=True)
class PreparedText:
    spoken_text: str
    info: TextPreparationInfo
    annotations: tuple[AnnotationSpan, ...]
    boundaries: tuple[BoundaryEvent, ...]
    source_map: SourceToSpokenMap
    consumed_substitutions: tuple[str, ...] = ()


class SSMDSubstitutionPreparer:
    """Apply only explicit SSMD ``sub`` aliases without automatic speech preparation."""

    def prepare(
        self,
        text: str,
        language: str,
        runs: tuple[LanguageRun, ...],
        annotations: tuple[AnnotationSpan, ...] = (),
        boundaries: tuple[BoundaryEvent, ...] = (),
        analyses: tuple[Any, ...] = (),
        parsed_document: ParsedDocument | None = None,
    ) -> PreparedText:
        del analyses  # SSMD substitutions do not need source linguistic analysis.
        if parsed_document is not None:
            if parsed_document.structural_text != text:
                raise TextPreparationError("SSMD source mapping does not match structural text")
            annotations = normalize_ssmd_substitution_spans(parsed_document, annotations)
        else:
            for annotation in annotations:
                if "sub" not in annotation.attrs:
                    continue
                start, end = annotation.structural_start, annotation.structural_end
                if type(start) is int and type(end) is int and 0 <= start < end <= len(text):
                    target = text[start:end]
                    if target[0].isspace() or target[-1].isspace():
                        raise PlanFormatError(
                            "SSMD sub annotation includes adjacent text that cannot be proven "
                            "to belong to the replacement target without a parser source mapping",
                            code="preparation.ssmd_sub_span_ambiguous",
                            path=f"$.annotations.{annotation.id}",
                        )
        active_runs = runs or (LanguageRun("lang-0", 0, len(text), language),)
        _validate_run_coverage(text, active_runs)

        edits: list[_MappedSubstitution] = []
        for annotation in annotations:
            if "sub" not in annotation.attrs:
                continue
            start, end = annotation.structural_start, annotation.structural_end
            alias = annotation.attrs["sub"]
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
                raise _ssmd_sub_error(
                    annotation, "substitution source range is empty or out of bounds"
                )
            if not isinstance(alias, str) or not alias.strip() or "\x00" in alias:
                raise _ssmd_sub_error(annotation, "sub alias must be a non-empty speech surface")
            conflicting = {"as", "say-as", "ph", "phonemes", "ipa", "sampa"}
            if conflicting.intersection(annotation.attrs):
                raise _ssmd_sub_error(
                    annotation, "sub cannot be combined with a pronunciation or say-as directive"
                )
            if not any(run.spoken_start <= start and end <= run.spoken_end for run in active_runs):
                raise _ssmd_sub_error(
                    annotation, "substitution must be contained in one language run"
                )

            for other in annotations:
                if other.id == annotation.id:
                    continue
                other_start, other_end = other.structural_start, other.structural_end
                overlaps = other_start < end and start < other_end
                splits_alias = start < other_start < end or start < other_end < end
                if overlaps and (
                    conflicting.intersection(other.attrs)
                    or (splits_alias and _has_speech_boundary_attrs(other.attrs))
                ):
                    raise _ssmd_sub_error(
                        annotation,
                        f"overlaps incompatible annotation {other.id} at "
                        f"[{other_start}:{other_end})",
                    )
                if (
                    other_start == other_end
                    and start < other_start < end
                    and _is_audio_annotation(other)
                ):
                    raise _ssmd_sub_error(
                        annotation,
                        f"contains authored media anchor from annotation {other.id}",
                    )

            for boundary in boundaries:
                if boundary.kind == "explicit" and start < boundary.position < end:
                    raise _ssmd_sub_error(
                        annotation,
                        f"contains explicit break boundary {boundary.id} at {boundary.position}",
                    )
            run = next(
                run for run in active_runs if run.spoken_start <= start and end <= run.spoken_end
            )
            edits.append(
                _MappedSubstitution(
                    source_start=start,
                    source_end=end,
                    output_start=0,
                    output_end=0,
                    source=text[start:end],
                    replacement=alias,
                    annotation_id=annotation.id,
                    language=run.language,
                )
            )

        edits.sort(key=lambda item: (item.source_start, item.source_end, item.annotation_id))
        previous_end = 0
        for edit in edits:
            if edit.source_start < previous_end:
                annotation = next(item for item in annotations if item.id == edit.annotation_id)
                raise _ssmd_sub_error(annotation, "overlaps another authored sub substitution")
            previous_end = edit.source_end

        output_parts: list[str] = []
        mapped_edits: list[_MappedSubstitution] = []
        source_cursor = 0
        output_cursor = 0
        for edit in edits:
            prefix = text[source_cursor : edit.source_start]
            output_parts.append(prefix)
            output_cursor += len(prefix)
            mapped = _MappedSubstitution(
                edit.source_start,
                edit.source_end,
                output_cursor,
                output_cursor + len(edit.replacement),
                edit.source,
                edit.replacement,
                edit.annotation_id,
                edit.language,
            )
            mapped_edits.append(mapped)
            output_parts.append(edit.replacement)
            output_cursor = mapped.output_end
            source_cursor = edit.source_end
        output_parts.append(text[source_cursor:])
        spoken = "".join(output_parts)
        source_map = _SSMDSourceToSpokenMap(len(text), len(spoken), tuple(mapped_edits))
        _validate_ssmd_map(text, spoken, mapped_edits, source_map)

        replacements = tuple(
            {
                "source_start": edit.source_start,
                "source_end": edit.source_end,
                "output_start": edit.output_start,
                "output_end": edit.output_end,
                "source": edit.source,
                "replacement": edit.replacement,
                "kind": "ssmd-sub",
                "rule": "ssmd.sub",
                "annotation_id": edit.annotation_id,
                "language": edit.language,
            }
            for edit in mapped_edits
        )
        mapped_annotations = tuple(
            _map_annotation(annotation, source_map) for annotation in annotations
        )
        mapped_boundaries = tuple(_map_boundary(boundary, source_map) for boundary in boundaries)
        info = TextPreparationInfo(
            backend="ssmd",
            version=None,
            languages=tuple(run.language for run in active_runs),
            replacements=replacements,
        )
        return PreparedText(
            spoken,
            info,
            mapped_annotations,
            mapped_boundaries,
            source_map,
            tuple(edit.annotation_id for edit in mapped_edits),
        )


class TTSReadyTextPreparer:
    def __init__(self, *, sequence_fallback_mode: str = "spell") -> None:
        if sequence_fallback_mode not in ("spell", "preserve"):
            raise ValueError("sequence_fallback_mode must be 'spell' or 'preserve'")
        self.sequence_fallback_mode = sequence_fallback_mode

    def prepare(
        self,
        text: str,
        language: str,
        runs: tuple[LanguageRun, ...],
        annotations: tuple[AnnotationSpan, ...] = (),
        boundaries: tuple[BoundaryEvent, ...] = (),
        analyses: tuple[RunAnalysis, ...] = (),
    ) -> PreparedText:
        try:
            import ttsready
        except ImportError as exc:
            raise TextPreparationError(str(exc)) from exc

        try:
            prepared_runs: list[Any] = []
            active_runs = runs or (LanguageRun("lang-0", 0, len(text), language),)
            _validate_run_coverage(text, active_runs)
            if len(analyses) > len(active_runs):
                raise TextPreparationError("source analysis count exceeds language run count")

            profile = _ttsready_profile(ttsready, self.sequence_fallback_mode)
            for run_index, run in enumerate(active_runs):
                local_text = text[run.spoken_start : run.spoken_end]
                analysis = analyses[run_index] if run_index < len(analyses) else None
                linguistic_tokens = _linguistic_tokens_for_run(ttsready, run, analysis)
                protected_spans = _protected_spans_for_run(ttsready, run, annotations)
                prepared_runs.append(
                    ttsready.prepare_run(
                        local_text,
                        language=language_lookup_key(run.language),
                        unit_id=run.id or f"run-{run_index}",
                        protected_spans=protected_spans,
                        linguistic_tokens=linguistic_tokens,
                        profile=profile,
                        strict=False,
                        preserve_run_boundaries=True,
                    )
                )

            for run, item in zip(active_runs, prepared_runs, strict=True):
                expected_length = run.spoken_end - run.spoken_start
                if item.source_map.source_length != expected_length:
                    raise TextPreparationError("TTSReady source map length does not match its run")
                if item.source_map.output_length != len(item.spoken_text):
                    raise TextPreparationError(
                        "TTSReady output map length does not match spoken text"
                    )

            spoken = "".join(item.spoken_text for item in prepared_runs)
            if sum(len(item.source_text) for item in prepared_runs) != len(text):
                raise TextPreparationError("TTSReady prepared runs do not cover the source text")
            source_map = ttsready.SourceOutputMap.concatenate(
                item.source_map for item in prepared_runs
            )
            if source_map.source_length != len(text):
                raise TextPreparationError("TTSReady concatenated source map length is invalid")
            if source_map.output_length != len(spoken):
                raise TextPreparationError("TTSReady concatenated output map length is invalid")

            replacements: list[dict[str, Any]] = []
            warnings: list[str] = []
            output_offset = 0
            for run, item in zip(active_runs, prepared_runs, strict=True):
                for change in item.changes:
                    value: dict[str, Any] = {
                        "source_start": change.source_start + run.spoken_start,
                        "source_end": change.source_end + run.spoken_start,
                        "output_start": change.output_start + output_offset,
                        "output_end": change.output_end + output_offset,
                        "source": change.source,
                        "replacement": change.replacement,
                        "kind": change.kind,
                    }
                    if change.language is not None:
                        value["language"] = change.language
                    if change.rule is not None:
                        value["rule"] = change.rule
                    replacements.append(value)
                warnings.extend(str(value) for value in item.warnings)
                output_offset += len(item.spoken_text)

            _validate_replacement_order(replacements)
            versions = ttsready.runtime_versions()
            raw_version = versions.get("spokenform")
            version_value = None if raw_version in (None, "", "unknown") else str(raw_version)
        except TextPreparationError:
            raise
        except ttsready.TTSReadyError as exc:
            raise TextPreparationError(str(exc)) from exc
        except (ImportError, TypeError, ValueError) as exc:
            raise TextPreparationError(str(exc)) from exc

        mapped_annotations = tuple(
            _map_annotation(annotation, source_map) for annotation in annotations
        )
        mapped_boundaries = tuple(_map_boundary(boundary, source_map) for boundary in boundaries)
        info = TextPreparationInfo(
            backend="spokenform",
            version=version_value,
            languages=tuple(run.language for run in runs),
            replacements=tuple(replacements),
            warnings=tuple(warnings),
        )
        return PreparedText(spoken, info, mapped_annotations, mapped_boundaries, source_map)


def _ttsready_profile(ttsready: Any, sequence_fallback_mode: str) -> Any:
    return ttsready.PreparationProfile(
        use_spacy=False,
        symbol_mode="none",
        normalize_unicode=True,
        normalize_whitespace=True,
        strip_outer_whitespace=False,
        collapse_horizontal_whitespace=True,
        normalize_line_whitespace=True,
        collapse_blank_lines=True,
        generic_acronym_mode="known_only",
        sequence_fallback_mode=sequence_fallback_mode,
        expand_abbreviations=True,
        expand_structured=True,
        expand_numbers=True,
    )


def _validate_run_coverage(text: str, runs: tuple[LanguageRun, ...]) -> None:
    position = 0
    for run in runs:
        if run.spoken_start != position or run.spoken_end < run.spoken_start:
            raise TextPreparationError("language runs must be contiguous and ordered")
        position = run.spoken_end
    if position != len(text):
        raise TextPreparationError("language runs do not cover the source text")


def _protected_spans_for_run(
    ttsready: Any,
    run: LanguageRun,
    annotations: tuple[AnnotationSpan, ...],
) -> tuple[Any, ...]:
    protected_keys = ("sub", "as", "say-as", "ph", "phonemes")
    return tuple(
        ttsready.ProtectedSpan(
            start=annotation.structural_start - run.spoken_start,
            end=annotation.structural_end - run.spoken_start,
            reason="ssmd.speech-directive",
        )
        for annotation in annotations
        if annotation.structural_start >= run.spoken_start
        and annotation.structural_end <= run.spoken_end
        and any(key in annotation.attrs for key in protected_keys)
    )


def _linguistic_tokens_for_run(
    ttsready: Any,
    run: LanguageRun,
    analysis: RunAnalysis | None,
) -> tuple[Any, ...]:
    if analysis is None:
        return ()
    if (
        analysis.start != run.spoken_start
        or analysis.end != run.spoken_end
        or analysis.language != run.language
    ):
        raise TextPreparationError("source analysis does not match its language run")

    result: list[Any] = []
    for token in analysis.tokens:
        if (
            token.spoken_start < run.spoken_start
            or token.spoken_end > run.spoken_end
            or token.spoken_end < token.spoken_start
        ):
            raise TextPreparationError("linguistic token falls outside its language run")
        result.append(
            ttsready.LinguisticToken(
                start=token.spoken_start - run.spoken_start,
                end=token.spoken_end - run.spoken_start,
                text=token.text,
                pos=token.pos,
                tag=token.tag,
                lemma=token.lemma,
                language=token.language or run.language,
            )
        )
    return tuple(result)


def _validate_replacement_order(replacements: list[dict[str, Any]]) -> None:
    previous_end = 0
    for replacement in replacements:
        start = replacement["source_start"]
        end = replacement["source_end"]
        if start < previous_end or end < start:
            raise TextPreparationError("TTSReady replacement ranges are overlapping or unordered")
        previous_end = end


class IdentityTextPreparer:
    def prepare(
        self,
        text: str,
        language: str,
        runs: tuple[LanguageRun, ...],
        annotations: tuple[AnnotationSpan, ...] = (),
        boundaries: tuple[BoundaryEvent, ...] = (),
        analyses: tuple[Any, ...] = (),
    ) -> PreparedText:
        source_map = _IdentitySourceMap(len(text))
        info = TextPreparationInfo(
            backend="identity",
            version=None,
            languages=tuple(run.language for run in runs),
        )
        return PreparedText(
            text,
            info,
            tuple(_map_annotation(annotation, source_map) for annotation in annotations),
            tuple(_map_boundary(boundary, source_map) for boundary in boundaries),
            source_map,
        )


@dataclass(frozen=True, slots=True)
class _MappedSubstitution:
    source_start: int
    source_end: int
    output_start: int
    output_end: int
    source: str
    replacement: str
    annotation_id: str
    language: str


class _SSMDSourceToSpokenMap:
    def __init__(
        self,
        source_length: int,
        output_length: int,
        edits: tuple[_MappedSubstitution, ...],
    ) -> None:
        self.source_length = source_length
        self.output_length = output_length
        self._edits = edits

    def map_source_position(self, position: int, *, bias: str = "left") -> int:
        if type(position) is not int or not 0 <= position <= self.source_length:
            raise ValueError("source position is outside the source text")
        if bias not in {"left", "right"}:
            raise ValueError("mapping bias must be 'left' or 'right'")
        offset = 0
        for edit in self._edits:
            if position < edit.source_start:
                return position + offset
            if position == edit.source_start:
                return edit.output_start
            if position < edit.source_end:
                return edit.output_start if bias == "left" else edit.output_end
            if position == edit.source_end:
                return edit.output_end
            offset = edit.output_end - edit.source_end
        return position + offset

    def map_output_position(self, position: int, *, bias: str = "left") -> int:
        if type(position) is not int or not 0 <= position <= self.output_length:
            raise ValueError("output position is outside the spoken text")
        if bias not in {"left", "right"}:
            raise ValueError("mapping bias must be 'left' or 'right'")
        offset = 0
        for edit in self._edits:
            if position < edit.output_start:
                return position + offset
            if position == edit.output_start:
                return edit.source_start
            if position < edit.output_end:
                return edit.source_start if bias == "left" else edit.source_end
            if position == edit.output_end:
                return edit.source_end
            offset = edit.source_end - edit.output_end
        return position + offset

    def map_source_span(self, start: int, end: int) -> tuple[int, int]:
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start <= end <= self.source_length
        ):
            raise ValueError("source span is outside the source text")
        return (
            self.map_source_position(start, bias="left"),
            self.map_source_position(end, bias="right"),
        )

    def map_output_span(self, start: int, end: int) -> tuple[int, int]:
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start <= end <= self.output_length
        ):
            raise ValueError("output span is outside the spoken text")
        return (
            self.map_output_position(start, bias="left"),
            self.map_output_position(end, bias="right"),
        )


def _ssmd_sub_error(annotation: AnnotationSpan, reason: str) -> PlanFormatError:
    source_range = ""
    if annotation.source_start is not None and annotation.source_end is not None:
        source_range = f"; SSMD source range [{annotation.source_start}:{annotation.source_end})"
    return PlanFormatError(
        f"annotation {annotation.id} structural range "
        f"[{annotation.structural_start}:{annotation.structural_end}){source_range}: {reason}",
        code="preparation.ssmd_sub_invalid",
        path=f"$.annotations.{annotation.id}",
    )


def _has_speech_boundary_attrs(attrs: Mapping[str, Any]) -> bool:
    return bool(
        {
            "lang",
            "voice",
            "voice-name",
            "emphasis",
            "rate",
            "pitch",
            "volume",
            "ph",
            "phonemes",
            "as",
            "say-as",
            "sub",
            "src",
        }.intersection(attrs)
    )


def _is_audio_annotation(annotation: AnnotationSpan) -> bool:
    return (
        annotation.kind == "audio"
        or "src" in annotation.attrs
        or annotation.attrs.get("tag") == "audio"
    )


def _validate_ssmd_map(
    source: str,
    spoken: str,
    edits: list[_MappedSubstitution],
    source_map: _SSMDSourceToSpokenMap,
) -> None:
    source_cursor = 0
    output_cursor = 0
    replay: list[str] = []
    previous_source = previous_output = -1
    for edit in edits:
        if (
            edit.source_start < source_cursor
            or edit.source_end <= edit.source_start
            or edit.source_end > len(source)
            or source[edit.source_start : edit.source_end] != edit.source
            or edit.output_start < output_cursor
            or edit.output_end <= edit.output_start
            or edit.output_end > len(spoken)
            or spoken[edit.output_start : edit.output_end] != edit.replacement
            or source_map.map_source_span(edit.source_start, edit.source_end)
            != (edit.output_start, edit.output_end)
            or source_map.map_output_span(edit.output_start, edit.output_end)
            != (edit.source_start, edit.source_end)
        ):
            raise PlanFormatError(
                f"SSMD substitution map is inconsistent at source range "
                f"[{edit.source_start}:{edit.source_end})",
                code="preparation.ssmd_map_invalid",
                path="$.source",
            )
        replay.extend((source[source_cursor : edit.source_start], edit.replacement))
        source_cursor = edit.source_end
        output_cursor = edit.output_end
        if edit.source_start < previous_source or edit.output_start < previous_output:
            raise PlanFormatError(
                "SSMD substitution map is not monotone",
                code="preparation.ssmd_map_invalid",
                path="$.source",
            )
        previous_source, previous_output = edit.source_end, edit.output_end
    replay.append(source[source_cursor:])
    if "".join(replay) != spoken or source_map.map_source_position(0) != 0:
        raise PlanFormatError(
            "SSMD substitutions do not replay to the exact spoken text",
            code="preparation.ssmd_map_invalid",
            path="$.source",
        )


class _IdentitySourceMap:
    def __init__(self, length: int) -> None:
        self.source_length = length
        self.output_length = length

    def map_source_span(self, start: int, end: int) -> tuple[int, int]:
        return start, end

    def map_output_span(self, start: int, end: int) -> tuple[int, int]:
        start = max(0, min(self.output_length, start))
        end = max(start, min(self.output_length, end))
        return start, end


def _map_annotation(annotation: AnnotationSpan, source_map: SourceToSpokenMap) -> AnnotationSpan:
    spoken_start, spoken_end = source_map.map_source_span(
        annotation.structural_start, annotation.structural_end
    )
    return AnnotationSpan(
        annotation.id,
        annotation.kind,
        annotation.attrs,
        annotation.structural_start,
        annotation.structural_end,
        spoken_start,
        max(spoken_start, spoken_end),
        annotation.source_start,
        annotation.source_end,
        annotation.source_node_id,
    )


def _map_source_point(source_map: SourceToSpokenMap, position: int, *, bias: str) -> int:
    mapper = getattr(source_map, "map_source_position", None)
    if callable(mapper):
        return mapper(position, bias=bias)
    return source_map.map_source_span(position, position)[0]


def _map_boundary(boundary: BoundaryEvent, source_map: SourceToSpokenMap) -> BoundaryEvent:
    anchor = str(boundary.attrs.get("anchor", "after"))
    bias = "right" if anchor == "after" else "left"
    position = _map_source_point(source_map, boundary.position, bias=bias)
    return BoundaryEvent(
        id=boundary.id,
        position=position,
        kind=boundary.kind,
        origin=boundary.origin,
        strength=boundary.strength,
        seconds=boundary.seconds,
        attrs=boundary.attrs,
    )
