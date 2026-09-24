from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Protocol

from .exceptions import TextPreparationError
from .language import LanguageRun, language_lookup_key
from .model import AnnotationSpan, BoundaryEvent, TextPreparationInfo


class SourceToSpokenMap(Protocol):
    source_length: int
    output_length: int

    def map_source_span(self, start: int, end: int) -> tuple[int, int]: ...


@dataclass(frozen=True, slots=True)
class PreparedText:
    spoken_text: str
    info: TextPreparationInfo
    annotations: tuple[AnnotationSpan, ...]
    boundaries: tuple[BoundaryEvent, ...]
    source_map: SourceToSpokenMap


class SpokenformTextPreparer:
    def prepare(
        self,
        text: str,
        language: str,
        runs: tuple[LanguageRun, ...],
        annotations: tuple[AnnotationSpan, ...] = (),
        boundaries: tuple[BoundaryEvent, ...] = (),
        analyses: tuple[Any, ...] = (),
    ) -> PreparedText:
        try:
            import spokenform

            prepared_runs: list[Any] = []
            active_runs = runs or (LanguageRun("lang-0", 0, len(text), language),)
            for run_index, run in enumerate(active_runs):
                local_text = text[run.spoken_start : run.spoken_end]
                protected = [
                    (
                        annotation.structural_start - run.spoken_start,
                        annotation.structural_end - run.spoken_start,
                    )
                    for annotation in annotations
                    if annotation.structural_start >= run.spoken_start
                    and annotation.structural_end <= run.spoken_end
                    and (annotation.attrs.get("ph") or annotation.attrs.get("phonemes"))
                ]
                kwargs: dict[str, Any] = {
                    "language": language_lookup_key(run.language),
                    "use_spacy": False,
                    "strip_outer_whitespace": False,
                    "preserve_run_boundaries": True,
                    "protected_spans": protected,
                }
                if run_index < len(analyses) and analyses[run_index].provider_doc is not None:
                    kwargs["nlp"] = analyses[run_index].provider_doc
                prepared_runs.append(spokenform.prepare(local_text, **kwargs))
            spoken = "".join(str(item.spoken_text) for item in prepared_runs)
            source_map = _compose_offsets(text, prepared_runs)
            replacements: list[dict[str, Any]] = []
            warnings: list[str] = []
            output_offset = 0
            for run, item in zip(
                runs or (LanguageRun("lang-0", 0, len(text), language),),
                prepared_runs,
                strict=False,
            ):
                for replacement in getattr(item, "source_replacements", ()):
                    value = _replacement_dict(replacement)
                    value["source_start"] = int(value.get("source_start", 0)) + run.spoken_start
                    value["source_end"] = int(value.get("source_end", 0)) + run.spoken_start
                    value["output_start"] = int(value.get("output_start", 0)) + output_offset
                    value["output_end"] = int(value.get("output_end", 0)) + output_offset
                    replacements.append(value)
                warnings.extend(str(value) for value in getattr(item, "warnings", ()))
                output_offset += len(str(item.spoken_text))
            try:
                ver = version("spokenform")
            except PackageNotFoundError:
                ver = None
        except (ImportError, ValueError, TypeError) as exc:
            raise TextPreparationError(str(exc)) from exc
        mapped_annotations = tuple(
            _map_annotation(annotation, source_map) for annotation in annotations
        )
        mapped_boundaries = tuple(_map_boundary(boundary, source_map) for boundary in boundaries)
        info = TextPreparationInfo(
            backend="spokenform",
            version=ver,
            languages=tuple(run.language for run in runs),
            replacements=tuple(replacements),
            warnings=tuple(warnings),
        )
        return PreparedText(spoken, info, mapped_annotations, mapped_boundaries, source_map)


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


class _CompositeSourceMap:
    def __init__(
        self,
        source_length: int,
        output_length: int,
        source_left: list[int],
        source_right: list[int],
    ) -> None:
        self.source_length = source_length
        self.output_length = output_length
        self.source_left = source_left
        self.source_right = source_right

    def map_source_span(self, start: int, end: int) -> tuple[int, int]:
        start = max(0, min(self.source_length, start))
        end = max(start, min(self.source_length, end))
        return self.source_left[start], self.source_right[end]


def _compose_offsets(text: str, prepared_runs: list[Any]) -> SourceToSpokenMap:
    if not prepared_runs:
        return _IdentitySourceMap(len(text))

    source_left: list[int] = []
    source_right: list[int] = []
    source_length = output_length = 0
    for item in prepared_runs:
        offset = getattr(item, "offset_map", None)
        if offset is None:
            raise TextPreparationError("spokenform did not provide an offset map")
        local_left = list(offset.source_left)
        local_right = list(offset.source_right)
        if not source_left:
            source_left.extend(value + output_length for value in local_left)
            source_right.extend(value + output_length for value in local_right)
        else:
            source_left.extend(value + output_length for value in local_left[1:])
            source_right.extend(value + output_length for value in local_right[1:])
        source_length += int(offset.source_length)
        output_length += int(offset.output_length)
    return _CompositeSourceMap(source_length, output_length, source_left, source_right)


def _replacement_dict(item: Any) -> dict[str, Any]:
    return {
        key: getattr(item, key)
        for key in (
            "source_start",
            "source_end",
            "output_start",
            "output_end",
            "source",
            "replacement",
            "kind",
            "rule",
            "language",
        )
        if hasattr(item, key)
    }


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
        boundary.id,
        position,
        boundary.kind,
        boundary.seconds,
        boundary.origin,
        boundary.strength,
        boundary.attrs,
    )
