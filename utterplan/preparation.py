from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .linguistics import RunAnalysis

from .exceptions import TextPreparationError
from .language import LanguageRun, language_lookup_key
from .model import AnnotationSpan, BoundaryEvent, TextPreparationInfo


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


def _map_boundary(boundary: BoundaryEvent, source_map: SourceToSpokenMap) -> BoundaryEvent:
    position, _ = source_map.map_source_span(boundary.position, boundary.position)
    return BoundaryEvent(
        id=boundary.id,
        position=position,
        kind=boundary.kind,
        origin=boundary.origin,
        strength=boundary.strength,
        seconds=boundary.seconds,
        attrs=boundary.attrs,
    )
