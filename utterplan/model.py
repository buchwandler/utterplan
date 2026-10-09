from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from ._version import __version__
from .config import semantic_config
from .exceptions import PlanFormatError, PlanValidationError, UnsupportedSchemaError
from .hashing import (
    FLOW_HASH_SCHEMA,
    UNIT_HASH_SCHEMA,
    flow_plan_id,
    flow_unit_hash,
    semantic_hash,
    unit_hash_payload,
)
from .language import LanguageRun
from .migration import migrate_plan_data
from .versioning import FORMAT, V4_SCHEMA_VERSION


def _plain(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


@dataclass(frozen=True, slots=True)
class PlanSource:
    format: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"format": self.format, "text": self.text}


@dataclass(frozen=True, slots=True)
class PlanTexts:
    structural: str
    spoken: str

    def to_dict(self) -> dict[str, str]:
        return {"structural": self.structural, "spoken": self.spoken}


@dataclass(frozen=True, slots=True)
class TextPreparationInfo:
    backend: str
    version: str | None
    languages: tuple[str, ...] = ()
    replacements: tuple[Mapping[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _plain(
            {
                "backend": self.backend,
                "version": self.version,
                "languages": self.languages,
                "replacements": self.replacements,
                "warnings": self.warnings,
            }
        )


@dataclass(frozen=True, slots=True)
class AnnotationSpan:
    """Annotation spans using structural, spoken, and original-source coordinates."""

    id: str
    kind: str
    attrs: Mapping[str, Any]
    structural_start: int
    structural_end: int
    spoken_start: int | None = None
    spoken_end: int | None = None
    source_start: int | None = None
    source_end: int | None = None
    source_node_id: str | None = None

    @property
    def char_start(self) -> int:
        """Structural start retained as a documented compatibility alias."""
        return self.structural_start

    @property
    def char_end(self) -> int:
        """Structural end retained as a documented compatibility alias."""
        return self.structural_end

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "attrs": _plain(self.attrs),
            "structural_start": self.structural_start,
            "structural_end": self.structural_end,
            "spoken_start": self.spoken_start,
            "spoken_end": self.spoken_end,
        }
        for key in ("source_start", "source_end", "source_node_id"):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        return result


@dataclass(frozen=True, slots=True)
class TokenAnnotation:
    spoken_start: int
    spoken_end: int
    text: str
    pos: str | None = None
    tag: str | None = None
    lemma: str | None = None
    language: str | None = None
    id: str | None = None

    morph: str | None = None

    @property
    def start(self) -> int:
        return self.spoken_start

    @property
    def end(self) -> int:
        return self.spoken_end

    def to_dict(self) -> dict[str, Any]:
        result = {
            "spoken_start": self.spoken_start,
            "spoken_end": self.spoken_end,
            "text": self.text,
        }
        for key, value in (
            ("pos", self.pos),
            ("tag", self.tag),
            ("lemma", self.lemma),
            ("language", self.language),
            ("morph", self.morph),
        ):
            if value is not None:
                result[key] = value
        if self.id is not None:
            result["id"] = self.id
        result["morph"] = self.morph
        return result


@dataclass(frozen=True, slots=True)
class LinguisticRun:
    language_run_id: str
    provider: Literal["spacy", "fallback", "unknown"]
    token_start: int
    token_end: int
    model: str | None = None
    provider_version: str | None = None
    model_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "language_run_id": self.language_run_id,
            "provider": self.provider,
            "token_start": self.token_start,
            "token_end": self.token_end,
            "model": self.model,
            "provider_version": self.provider_version,
            "model_version": self.model_version,
        }


@dataclass(frozen=True, slots=True)
class BoundaryEvent:
    id: str
    position: int
    kind: str
    origin: str = "planner"
    strength: str | None = None
    attrs: Mapping[str, Any] = field(default_factory=dict)
    seconds: int | float | None = None

    @property
    def pos(self) -> int:
        return self.position

    def to_dict(self) -> dict[str, Any]:
        result = {
            "id": self.id,
            "position": self.position,
            "kind": self.kind,
            "seconds": self.seconds,
            "origin": self.origin,
            "strength": self.strength,
        }
        if self.attrs:
            result["attrs"] = _plain(self.attrs)
        return result


@dataclass(frozen=True, slots=True)
class SemanticBoundary:
    """Stable semantic split point in spoken-text coordinates."""

    id: str
    position: int
    kind: str
    origin: str = "planner"
    language_run_id: str | None = None
    attrs: Mapping[str, Any] = field(default_factory=dict)

    @property
    def spoken_position(self) -> int:
        return self.position

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "position": self.position,
            "kind": self.kind,
            "origin": self.origin,
            "language_run_id": self.language_run_id,
        }
        if self.attrs:
            result["attrs"] = _plain(self.attrs)
        return result


@dataclass(frozen=True, slots=True)
class VoiceDirective:
    reference: str | None = None
    name: str | None = None
    languages: str | None = None
    gender: str | None = None
    age: int | None = None
    variant: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in (
                ("reference", self.reference),
                ("name", self.name),
                ("languages", self.languages),
                ("gender", self.gender),
                ("age", self.age),
                ("variant", self.variant),
            )
            if value is not None
        }


@dataclass(frozen=True, slots=True)
class PronunciationDirective:
    phonemes: str
    alphabet: str = "ipa"

    def to_dict(self) -> dict[str, str]:
        return {"phonemes": self.phonemes, "alphabet": self.alphabet}


@dataclass(frozen=True, slots=True)
class ProsodyDirective:
    rate: str | None = None
    pitch: str | None = None
    volume: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {"rate": self.rate, "pitch": self.pitch, "volume": self.volume}


@dataclass(frozen=True, slots=True)
class EmphasisDirective:
    level: str

    def to_dict(self) -> dict[str, str]:
        return {"level": self.level}


@dataclass(frozen=True, slots=True)
class SayAsDirective:
    interpret_as: str
    format: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "interpret_as": self.interpret_as,
            "format": self.format,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class SubstitutionDirective:
    alias: str

    def to_dict(self) -> dict[str, str]:
        return {"alias": self.alias}


@dataclass(frozen=True, slots=True)
class ExtensionDirective:
    name: str
    params: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "params": dict(self.params)}


@dataclass(frozen=True, slots=True)
class AudioDirective:
    src: str
    alt_text: str | None = None
    clip_begin: str | None = None
    clip_end: str | None = None
    speed: str | None = None
    repeat_duration: str | None = None
    repeat_count: float | None = None
    sound_level: str | None = None
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "src": self.src,
            "alt_text": self.alt_text,
            "clip_begin": self.clip_begin,
            "clip_end": self.clip_end,
            "speed": self.speed,
            "repeat_duration": self.repeat_duration,
            "repeat_count": self.repeat_count,
            "sound_level": self.sound_level,
        }
        if self.description is not None:
            result["description"] = self.description
        return result


@dataclass(frozen=True, slots=True)
class SegmentDirectives:
    voice: VoiceDirective | None = None
    pronunciation: PronunciationDirective | None = None
    prosody: ProsodyDirective | None = None
    emphasis: EmphasisDirective | None = None
    audio: AudioDirective | None = None
    say_as: SayAsDirective | None = None
    substitution: SubstitutionDirective | None = None
    extensions: tuple[ExtensionDirective, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in (
            ("voice", self.voice),
            ("pronunciation", self.pronunciation),
            ("prosody", self.prosody),
            ("emphasis", self.emphasis),
            ("say_as", self.say_as),
            ("substitution", self.substitution),
            ("audio", self.audio),
        ):
            if value is not None:
                result[key] = _plain(value)
        if self.extensions:
            result["extensions"] = [_plain(item) for item in self.extensions]
        return result


@dataclass(frozen=True, slots=True)
class PlanSegment:
    id: str
    text: str
    spoken_start: int
    spoken_end: int
    language: str
    paragraph: int = 0
    sentence: int = 0
    clause: int = 0
    structural_start: int | None = None
    structural_end: int | None = None
    pause_before: PauseIntent | LegacyPause | None = None
    pause_after: PauseIntent | LegacyPause | None = None
    directives: SegmentDirectives = field(default_factory=SegmentDirectives)
    token_indices: tuple[int, ...] = ()
    annotation_ids: tuple[str, ...] = ()

    @property
    def char_start(self) -> int:
        return self.spoken_start

    @property
    def char_end(self) -> int:
        return self.spoken_end

    @property
    def paragraph_idx(self) -> int:
        return self.paragraph

    @property
    def sentence_idx(self) -> int:
        return self.sentence

    @property
    def clause_idx(self) -> int:
        return self.clause

    @property
    def meta(self) -> dict[str, Any]:
        return {"language": self.language}

    def to_dict(self) -> dict[str, Any]:
        result = {
            "id": self.id,
            "text": self.text,
            "spoken_start": self.spoken_start,
            "spoken_end": self.spoken_end,
            "language": self.language,
            "paragraph": self.paragraph,
            "sentence": self.sentence,
            "clause": self.clause,
            "directives": self.directives.to_dict(),
            "token_indices": list(self.token_indices),
            "annotation_ids": list(self.annotation_ids),
        }
        if self.pause_before is not None:
            result["pause_before"] = self.pause_before.to_dict()
        if self.pause_after is not None:
            result["pause_after"] = self.pause_after.to_dict()
        if self.structural_start is not None:
            result["structural_start"] = self.structural_start
        if self.structural_end is not None:
            result["structural_end"] = self.structural_end
        return result


@dataclass(frozen=True, slots=True)
class Marker:
    id: str
    name: str
    spoken_position: int
    attrs: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = {"id": self.id, "name": self.name, "spoken_position": self.spoken_position}
        if self.attrs:
            result["attrs"] = _plain(self.attrs)
        return result


@dataclass(frozen=True, slots=True)
class PlanUnit:
    id: str
    index: int
    kind: str
    spoken_start: int
    spoken_end: int
    segment_ids: tuple[str, ...]
    marker_ids: tuple[str, ...] = ()
    content_hash: str = ""
    content_hash_schema: str = UNIT_HASH_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "index": self.index,
            "kind": self.kind,
            "spoken_start": self.spoken_start,
            "spoken_end": self.spoken_end,
            "segment_ids": list(self.segment_ids),
            "marker_ids": list(self.marker_ids),
            "content_hash": self.content_hash,
            "content_hash_schema": self.content_hash_schema,
        }


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str
    severity: str = "info"
    path: str | None = None
    source_start: int | None = None
    source_end: int | None = None
    line: int | None = None
    column: int | None = None
    hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "path": self.path,
        }
        for key in ("source_start", "source_end", "line", "column", "hint"):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        return result


@dataclass(frozen=True, slots=True)
class UtterancePlan:
    source: PlanSource
    config: Mapping[str, Any]
    texts: PlanTexts
    preparation: TextPreparationInfo
    languages: tuple[LanguageRun, ...] = ()
    annotations: tuple[AnnotationSpan, ...] = ()
    linguistic_runs: tuple[LinguisticRun, ...] = ()
    semantic_boundaries: tuple[SemanticBoundary, ...] = ()
    boundaries: tuple[BoundaryEvent, ...] = ()
    tokens: tuple[TokenAnnotation, ...] = ()
    segments: tuple[PlanSegment, ...] = ()
    units: tuple[PlanUnit, ...] = ()
    markers: tuple[Marker, ...] = ()
    document_metadata: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    plan_id: str = ""
    producer: Mapping[str, Any] = field(
        default_factory=lambda: {"name": FORMAT, "version": __version__}
    )
    format: str = FORMAT
    schema_version: int = V4_SCHEMA_VERSION

    def semantic_dict(self) -> dict[str, Any]:
        data = self.to_dict()
        for key in ("plan_id", "producer", "diagnostics", "warnings"):
            data.pop(key, None)
        data["config"] = semantic_config(data["config"])
        return data

    def with_identity(self) -> UtterancePlan:
        return (
            self
            if self.plan_id == semantic_hash(self.semantic_dict())
            else _replace_plan(self, plan_id=semantic_hash(self.semantic_dict()))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "schema_version": self.schema_version,
            "producer": _plain(self.producer),
            "plan_id": self.plan_id,
            "source": self.source.to_dict(),
            "config": _plain(self.config),
            "texts": self.texts.to_dict(),
            "preparation": self.preparation.to_dict(),
            "languages": [_plain(x) for x in self.languages],
            "linguistic_runs": [_plain(x) for x in self.linguistic_runs],
            "annotations": [_plain(x) for x in self.annotations],
            "semantic_boundaries": [_plain(x) for x in self.semantic_boundaries],
            "boundaries": [_plain(x) for x in self.boundaries],
            "tokens": [_plain(x) for x in self.tokens],
            "segments": [_plain(x) for x in self.segments],
            "units": [_plain(x) for x in self.units],
            "markers": [_plain(x) for x in self.markers],
            "document_metadata": _plain(self.document_metadata),
            "warnings": list(self.warnings),
            "diagnostics": [_plain(x) for x in self.diagnostics],
        }

    def to_toml(self) -> str:
        """Return the canonical human-readable TOML representation."""
        from .toml_codec import dumps_toml

        return dumps_toml(self)

    def save(self, path: str | Path) -> None:
        """Atomically save this plan as TOML."""
        from .atomic_io import atomic_write_text

        atomic_write_text(path, self.to_toml(), create_parent=True)

    @classmethod
    def from_toml(cls, value: str) -> UtterancePlan:
        """Decode a TOML representation of a semantic schema-v4 plan."""
        from .codecs.v4_toml import loads_toml

        return loads_toml(value)

    @classmethod
    def load(cls, path: str | Path) -> UtterancePlan:
        """Load a canonical TOML plan; JSON is never auto-detected."""
        source = Path(path)
        if source.suffix.lower() == ".json":
            raise PlanFormatError(
                "JSON is not a supported plan-file format; use 'utterplan migrate' to convert it to TOML",
                code="format.unsupported_json",
            )
        return cls.from_toml(source.read_text(encoding="utf-8"))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> UtterancePlan:
        migrated = migrate_plan_data(data, target_version=V4_SCHEMA_VERSION)
        _check_shape(migrated.data)
        try:
            plan = _from_current_dict(migrated.data)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise PlanFormatError(f"invalid plan value: {exc}", code="plan.value") from exc
        plan.validate()
        return plan

    def validate(self) -> None:
        validate_plan(self)

    def tokens_for_segment(self, segment: PlanSegment | str) -> tuple[TokenAnnotation, ...]:
        if isinstance(segment, str):
            segment = next(item for item in self.segments if item.id == segment)
        return tuple(self.tokens[index] for index in segment.token_indices)

    def semantic_boundaries_in_range(
        self,
        start: int,
        end: int,
        *,
        kinds: Iterable[str] | None = None,
        interior_only: bool = True,
    ) -> tuple[SemanticBoundary, ...]:
        """Return semantic boundaries within a spoken-text coordinate range."""
        if (
            type(start) is not int
            or type(end) is not int
            or not (0 <= start <= end <= len(self.texts.spoken))
        ):
            raise ValueError("range must be valid spoken-text coordinates")
        selected_kinds = None if kinds is None else frozenset(kinds)
        if interior_only:
            matches = (
                boundary for boundary in self.semantic_boundaries if start < boundary.position < end
            )
        else:
            matches = (
                boundary
                for boundary in self.semantic_boundaries
                if start <= boundary.position <= end
            )
        if selected_kinds is not None:
            matches = (boundary for boundary in matches if boundary.kind in selected_kinds)
        return tuple(
            sorted(
                matches,
                key=lambda boundary: (
                    boundary.position,
                    boundary.kind,
                    boundary.id,
                ),
            )
        )

    def semantic_boundaries_for_segment(
        self,
        segment: PlanSegment | str,
        *,
        kinds: Iterable[str] | None = None,
    ) -> tuple[SemanticBoundary, ...]:
        """Return semantic boundaries internal to a plan segment."""
        if isinstance(segment, str):
            segment = next(item for item in self.segments if item.id == segment)
        return self.semantic_boundaries_in_range(
            segment.spoken_start,
            segment.spoken_end,
            kinds=kinds,
        )


def _replace_plan(plan: UtterancePlan, **changes: Any) -> UtterancePlan:
    values = {field: getattr(plan, field) for field in plan.__dataclass_fields__}
    values.update(changes)
    return UtterancePlan(**values)


def _check_shape(data: Mapping[str, Any]) -> None:
    if not isinstance(data, Mapping):
        raise PlanFormatError("plan must be an object", code="json.type")
    if data.get("format") != FORMAT:
        raise PlanFormatError("format must be 'utterplan'", code="format.invalid", path="$.format")
    allowed = {
        "format",
        "schema_version",
        "producer",
        "plan_id",
        "source",
        "config",
        "texts",
        "preparation",
        "languages",
        "linguistic_runs",
        "annotations",
        "semantic_boundaries",
        "boundaries",
        "tokens",
        "segments",
        "units",
        "markers",
        "document_metadata",
        "warnings",
        "diagnostics",
    }
    unknown = set(data) - allowed
    if unknown:
        raise PlanFormatError(f"unknown top-level fields: {sorted(unknown)}", code="field.unknown")
    if data.get("schema_version") != V4_SCHEMA_VERSION:
        raise UnsupportedSchemaError(data.get("schema_version"))
    for key in ("source", "config", "texts", "preparation", "segments", "units", "linguistic_runs"):
        if key not in data:
            raise PlanFormatError(
                f"required field {key!r} is missing", code="field.required", path=f"$.{key}"
            )

    _check_nested_types(data)


def _check_nested_types(data: Mapping[str, Any]) -> None:
    _expect(data.get("producer"), Mapping, "$.producer")
    _expect(data.get("source"), Mapping, "$.source")
    _expect(data["source"].get("format"), str, "$.source.format")
    _expect(data["source"].get("text"), str, "$.source.text")
    _expect(data.get("config"), Mapping, "$.config")
    texts = _expect(data.get("texts"), Mapping, "$.texts")
    _expect(texts.get("structural"), str, "$.texts.structural")
    _expect(texts.get("spoken"), str, "$.texts.spoken")
    preparation = _expect(data.get("preparation"), Mapping, "$.preparation")
    unknown = set(preparation) - {"backend", "version", "languages", "replacements", "warnings"}
    if unknown:
        raise PlanFormatError(
            f"unknown preparation fields: {sorted(unknown)}",
            code="field.unknown",
            path="$.preparation",
        )
    _expect(preparation.get("backend"), str, "$.preparation.backend")
    if preparation.get("version") is not None:
        _expect(preparation.get("version"), str, "$.preparation.version")
    for key in ("languages", "replacements", "warnings"):
        _expect(preparation.get(key), list, f"$.preparation.{key}")
    for key in (
        "languages",
        "annotations",
        "semantic_boundaries",
        "boundaries",
        "tokens",
        "linguistic_runs",
        "segments",
        "units",
        "markers",
        "warnings",
        "diagnostics",
    ):
        _expect(data.get(key, [] if key == "semantic_boundaries" else None), list, f"$.{key}")
    for index, item in enumerate(data.get("semantic_boundaries", ())):
        value = _expect(item, Mapping, f"$.semantic_boundaries[{index}]")
        for key in ("id", "kind", "origin"):
            _expect(value.get(key), str, f"$.semantic_boundaries[{index}].{key}")
        _expect(value.get("position"), int, f"$.semantic_boundaries[{index}].position")
        if "language_run_id" not in value:
            raise PlanFormatError(
                "language_run_id is required",
                code="field.required",
                path=f"$.semantic_boundaries[{index}].language_run_id",
            )
        if value["language_run_id"] is not None:
            _expect(
                value["language_run_id"],
                str,
                f"$.semantic_boundaries[{index}].language_run_id",
            )
        if "attrs" in value:
            _expect(value["attrs"], Mapping, f"$.semantic_boundaries[{index}].attrs")
    for index, item in enumerate(data["languages"]):
        value = _expect(item, Mapping, f"$.languages[{index}]")
        _expect(value.get("id"), str, f"$.languages[{index}].id")
        _expect(value.get("spoken_start"), int, f"$.languages[{index}].spoken_start")
        _expect(value.get("spoken_end"), int, f"$.languages[{index}].spoken_end")
        _expect(value.get("language"), str, f"$.languages[{index}].language")

    for index, item in enumerate(data["linguistic_runs"]):
        value = _expect(item, Mapping, f"$.linguistic_runs[{index}]")
        for key in ("language_run_id", "provider"):
            _expect(value.get(key), str, f"$.linguistic_runs[{index}].{key}")
        for key in ("token_start", "token_end"):
            _expect(value.get(key), int, f"$.linguistic_runs[{index}].{key}")
        for key in ("model", "provider_version", "model_version"):
            if value.get(key) is not None:
                _expect(value.get(key), str, f"$.linguistic_runs[{index}].{key}")

    for index, item in enumerate(data["annotations"]):
        value = _expect(item, Mapping, f"$.annotations[{index}]")
        for key in ("id", "kind"):
            _expect(value.get(key), str, f"$.annotations[{index}].{key}")
        for key in ("structural_start", "structural_end"):
            _expect(value.get(key), int, f"$.annotations[{index}].{key}")
        for key in ("spoken_start", "spoken_end"):
            if value.get(key) is not None:
                _expect(value.get(key), int, f"$.annotations[{index}].{key}")
        _expect(value.get("attrs"), Mapping, f"$.annotations[{index}].attrs")
    for index, item in enumerate(data["tokens"]):
        value = _expect(item, Mapping, f"$.tokens[{index}]")
        for key in ("spoken_start", "spoken_end"):
            _expect(value.get(key), int, f"$.tokens[{index}].{key}")
        _expect(value.get("text"), str, f"$.tokens[{index}].text")
        for key in ("pos", "tag", "lemma", "language", "morph"):
            if value.get(key) is not None:
                _expect(value.get(key), str, f"$.tokens[{index}].{key}")

    for index, item in enumerate(data["segments"]):
        value = _expect(item, Mapping, f"$.segments[{index}]")
        _expect(value.get("text"), str, f"$.segments[{index}].text")
        for key in ("spoken_start", "spoken_end"):
            _expect(value.get(key), int, f"$.segments[{index}].{key}")
        _expect(value.get("language"), str, f"$.segments[{index}].language")
        for key in ("token_indices", "annotation_ids"):
            _expect(value.get(key), list, f"$.segments[{index}].{key}")
    for index, item in enumerate(data["units"]):
        value = _expect(item, Mapping, f"$.units[{index}]")
        for key in ("id", "kind", "content_hash", "content_hash_schema"):
            _expect(value.get(key), str, f"$.units[{index}].{key}")
        _expect(value.get("segment_ids"), list, f"$.units[{index}].segment_ids")
        _expect(value.get("marker_ids"), list, f"$.units[{index}].marker_ids")
    for index, item in enumerate(data["markers"]):
        value = _expect(item, Mapping, f"$.markers[{index}]")
        for key in ("id", "name"):
            _expect(value.get(key), str, f"$.markers[{index}].{key}")
        _expect(value.get("spoken_position"), int, f"$.markers[{index}].spoken_position")
    for index, item in enumerate(data["warnings"]):
        _expect(item, str, f"$.warnings[{index}]")


def _expect(value: Any, expected: type | tuple[type, ...], path: str) -> Any:
    valid = type(value) is int if expected is int else isinstance(value, expected)
    if not valid:
        raise PlanFormatError(f"expected {expected} at {path}", code="field.type", path=path)
    return value


def _pause(data: Any) -> PauseIntent | None:
    if data is None:
        return None
    if isinstance(data, str):
        return PauseIntent(cast(Any, data))
    if not isinstance(data, Mapping):
        raise PlanFormatError("pause intent must be a string or inline table", code="pause.type")
    if data.get("type") == "timed":
        if set(data) != {"type", "time"}:
            raise PlanFormatError(
                "timed pause table must contain only type and time", code="pause.type"
            )
        time = data.get("time")
        if not isinstance(time, str):
            raise PlanFormatError("timed pause requires an exact time token", code="pause.time")
        return PauseIntent("timed", time)
    if "seconds" in data or "events" in data:
        raise PlanFormatError(
            "numeric v4 pause must be migrated before current-model decoding",
            code="pause.legacy_numeric",
        )
    raise PlanFormatError("invalid pause intent table", code="pause.type")


def _legacy_pause(data: Any) -> PauseIntent | LegacyPause | None:
    if data is None:
        return None
    if isinstance(data, Mapping) and ("seconds" in data or "events" in data):
        seconds = data.get("seconds")
        events = data.get("events")
        if type(seconds) not in {int, float} or not isinstance(events, (list, tuple)):
            raise PlanFormatError("invalid schema-v4 pause payload", code="pause.legacy_numeric")
        seconds_value = cast(int | float, seconds)
        if (
            not math.isfinite(seconds_value)
            or seconds_value < 0
            or any(not isinstance(item, str) for item in events)
        ):
            raise PlanFormatError("invalid schema-v4 pause payload", code="pause.legacy_numeric")
        return LegacyPause(seconds_value, tuple(events))
    return _pause(data)


def _directive(data: Mapping[str, Any] | None) -> SegmentDirectives:
    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        raise PlanFormatError("directives must be an object", code="segment.directives")
    allowed = {
        "voice",
        "pronunciation",
        "prosody",
        "emphasis",
        "say_as",
        "substitution",
        "audio",
        "extensions",
    }
    unknown = set(data) - allowed
    if unknown:
        raise PlanFormatError(f"unknown directive fields: {sorted(unknown)}", code="field.unknown")
    voice = data.get("voice")
    pronunciation = data.get("pronunciation")
    prosody = data.get("prosody")
    emphasis = data.get("emphasis")
    say_as = data.get("say_as")
    substitution = data.get("substitution")
    audio = data.get("audio")
    return SegmentDirectives(
        voice=VoiceDirective(
            reference=voice.get("reference"),
            name=voice.get("name"),
            languages=voice.get("languages"),
            gender=voice.get("gender"),
            age=_optional_int(voice.get("age")),
            variant=_optional_int(voice.get("variant")),
        )
        if voice
        else None,
        pronunciation=PronunciationDirective(
            str(pronunciation["phonemes"]), str(pronunciation.get("alphabet", "ipa"))
        )
        if pronunciation
        else None,
        prosody=ProsodyDirective(prosody.get("rate"), prosody.get("pitch"), prosody.get("volume"))
        if prosody
        else None,
        emphasis=EmphasisDirective(str(emphasis["level"])) if emphasis else None,
        say_as=SayAsDirective(
            str(say_as["interpret_as"]), say_as.get("format"), say_as.get("detail")
        )
        if say_as
        else None,
        substitution=SubstitutionDirective(str(substitution["alias"])) if substitution else None,
        audio=AudioDirective(
            src=str(audio["src"]),
            description=audio.get("description"),
            clip_begin=audio.get("clip_begin"),
            clip_end=audio.get("clip_end"),
            speed=audio.get("speed"),
            repeat_duration=audio.get("repeat_duration"),
            repeat_count=audio.get("repeat_count"),
            sound_level=audio.get("sound_level"),
            alt_text=audio.get("alt_text"),
        )
        if audio
        else None,
        extensions=tuple(
            ExtensionDirective(str(item["name"]), dict(item.get("params", {})))
            for item in data.get("extensions", ())
        ),
    )


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _from_current_dict(data: Mapping[str, Any]) -> UtterancePlan:
    source = data["source"]
    texts = data["texts"]
    prep = data["preparation"]
    return UtterancePlan(
        source=PlanSource(str(source["format"]), str(source["text"])),
        config=dict(data["config"]),
        texts=PlanTexts(str(texts["structural"]), str(texts["spoken"])),
        preparation=TextPreparationInfo(
            backend=str(prep["backend"]),
            version=prep.get("version"),
            languages=tuple(prep["languages"]),
            replacements=tuple(prep["replacements"]),
            warnings=tuple(prep["warnings"]),
        ),
        languages=tuple(
            LanguageRun(
                str(x["id"]),
                int(x["spoken_start"]),
                int(x["spoken_end"]),
                str(x["language"]),
                str(x.get("source", "document-default")),
            )
            for x in data.get("languages", ())
        ),
        linguistic_runs=tuple(
            LinguisticRun(
                language_run_id=str(x["language_run_id"]),
                provider=cast(Literal["spacy", "fallback", "unknown"], str(x["provider"])),
                token_start=int(x["token_start"]),
                token_end=int(x["token_end"]),
                model=x.get("model"),
                provider_version=x.get("provider_version"),
                model_version=x.get("model_version"),
            )
            for x in data.get("linguistic_runs", ())
        ),
        annotations=tuple(
            AnnotationSpan(
                id=str(x.get("id", f"annotation-{i:06d}")),
                kind=str(x.get("kind", "annotation")),
                attrs=dict(x.get("attrs", {})),
                structural_start=int(x.get("structural_start", x.get("char_start", 0))),
                structural_end=int(x.get("structural_end", x.get("char_end", 0))),
                spoken_start=_optional_int(x.get("spoken_start")),
                spoken_end=_optional_int(x.get("spoken_end")),
                source_start=_optional_int(x.get("source_start")),
                source_end=_optional_int(x.get("source_end")),
                source_node_id=x.get("source_node_id"),
            )
            for i, x in enumerate(data.get("annotations", ()))
        ),
        semantic_boundaries=tuple(
            SemanticBoundary(
                str(x["id"]),
                int(x["position"]),
                str(x["kind"]),
                str(x["origin"]),
                x.get("language_run_id"),
                dict(x.get("attrs", {})),
            )
            for x in data.get("semantic_boundaries", ())
        ),
        boundaries=tuple(
            BoundaryEvent(
                id=str(x["id"]),
                position=int(x.get("position", x.get("pos", 0))),
                kind=str(x["kind"]),
                origin=str(x.get("origin", "planner")),
                seconds=x.get("seconds"),
                strength=x.get("strength"),
                attrs={
                    **dict(x.get("attrs", {})),
                },
            )
            for x in data.get("boundaries", ())
        ),
        tokens=tuple(
            TokenAnnotation(
                int(x["spoken_start"]),
                int(x["spoken_end"]),
                str(x.get("text", "")),
                x.get("pos"),
                x.get("tag"),
                x.get("lemma"),
                x.get("language"),
                x.get("id"),
                x.get("morph"),
            )
            for x in data.get("tokens", ())
        ),
        segments=tuple(
            PlanSegment(
                str(x["id"]),
                str(x["text"]),
                int(x["spoken_start"]),
                int(x["spoken_end"]),
                str(x.get("language", "")),
                int(x.get("paragraph", 0)),
                int(x.get("sentence", 0)),
                int(x.get("clause", 0)),
                x.get("structural_start"),
                x.get("structural_end"),
                _legacy_pause(x.get("pause_before")),
                _legacy_pause(x.get("pause_after")),
                _directive(x.get("directives")),
                tuple(x.get("token_indices", ())),
                tuple(x.get("annotation_ids", ())),
            )
            for x in data.get("segments", ())
        ),
        units=tuple(
            PlanUnit(
                str(x["id"]),
                int(x["index"]),
                str(x["kind"]),
                int(x["spoken_start"]),
                int(x["spoken_end"]),
                tuple(x.get("segment_ids", ())),
                tuple(x.get("marker_ids", ())),
                str(x.get("content_hash", "")),
                str(x.get("content_hash_schema", UNIT_HASH_SCHEMA)),
            )
            for x in data.get("units", ())
        ),
        markers=tuple(
            Marker(
                str(x["id"]),
                str(x["name"]),
                int(x.get("spoken_position", x.get("position", 0))),
                dict(x.get("attrs", {})),
            )
            for x in data.get("markers", ())
        ),
        document_metadata=dict(data.get("document_metadata", {})),
        warnings=tuple(data.get("warnings", ())),
        diagnostics=tuple(
            Diagnostic(
                code=str(x["code"]),
                message=str(x["message"]),
                severity=str(x.get("severity", "info")),
                path=x.get("path"),
                source_start=x.get("source_start"),
                source_end=x.get("source_end"),
                line=x.get("line"),
                column=x.get("column"),
                hint=x.get("hint"),
            )
            for x in data.get("diagnostics", ())
        ),
        plan_id=str(data.get("plan_id", "")),
        producer=dict(data.get("producer", {"name": FORMAT, "version": __version__})),
        format=str(data["format"]),
        schema_version=int(data["schema_version"]),
    )


def validate_plan_structure(plan: UtterancePlan) -> None:
    text = plan.texts.spoken
    if plan.source.format not in {"plain", "ssmd"}:
        raise PlanValidationError("unsupported source format", code="source.format")
    if plan.source.text is None:
        raise PlanValidationError("source text is required", code="source.text")
    ids: set[str] = set()
    for collection, _name in (
        (plan.languages, "language"),
        (plan.annotations, "annotation"),
        (plan.semantic_boundaries, "semantic boundary"),
        (plan.boundaries, "boundary"),
        (plan.tokens, "token"),
        (plan.segments, "segment"),
        (plan.units, "unit"),
        (plan.markers, "marker"),
    ):
        for item in collection:
            item_id = getattr(item, "id", None)
            if item_id is not None and item_id in ids:
                raise PlanValidationError(f"duplicate id {item_id}", code="id.duplicate")
            if item_id is not None:
                ids.add(item_id)
    semantic_keys: set[tuple[int, str]] = set()
    previous_semantic_key: tuple[int, str, str, str] | None = None
    language_ids = {run.id for run in plan.languages}
    for index, boundary in enumerate(plan.semantic_boundaries):
        path = f"$.semantic_boundaries[{index}]"
        if not isinstance(boundary.id, str) or not boundary.id:
            raise PlanValidationError(
                "semantic boundary id must be non-empty",
                code="semantic_boundary.id",
                path=f"{path}.id",
            )
        if type(boundary.position) is not int or not (0 <= boundary.position <= len(text)):
            raise PlanValidationError(
                "semantic boundary position is outside spoken text",
                code="semantic_boundary.out_of_range",
                path=f"{path}.position",
            )
        if not isinstance(boundary.kind, str) or not boundary.kind:
            raise PlanValidationError(
                "semantic boundary kind must be non-empty",
                code="semantic_boundary.kind",
                path=f"{path}.kind",
            )
        if not isinstance(boundary.origin, str) or not boundary.origin:
            raise PlanValidationError(
                "semantic boundary origin must be non-empty",
                code="semantic_boundary.origin",
                path=f"{path}.origin",
            )
        if boundary.kind in {"clause", "parenthetical"} and not (0 < boundary.position < len(text)):
            raise PlanValidationError(
                f"{boundary.kind} boundaries must be interior to spoken text",
                code="semantic_boundary.not_interior",
                path=f"{path}.position",
            )
        if boundary.language_run_id is not None and boundary.language_run_id not in language_ids:
            raise PlanValidationError(
                "semantic boundary references unknown language run",
                code="semantic_boundary.unknown_language_run",
                path=f"{path}.language_run_id",
            )
        duplicate_key = (boundary.position, boundary.kind)
        if duplicate_key in semantic_keys:
            raise PlanValidationError(
                "duplicate semantic boundary kind and position",
                code="semantic_boundary.duplicate",
                path=path,
            )
        semantic_keys.add(duplicate_key)
        sort_key = (boundary.position, boundary.kind, boundary.origin, boundary.id)
        if previous_semantic_key is not None and sort_key < previous_semantic_key:
            raise PlanValidationError(
                "semantic boundaries are not in canonical order",
                code="semantic_boundary.order",
                path=path,
            )
        previous_semantic_key = sort_key
        if not isinstance(boundary.attrs, Mapping):
            raise PlanValidationError(
                "semantic boundary attrs must be a mapping",
                code="semantic_boundary.attrs",
                path=f"{path}.attrs",
            )
        try:
            json.dumps(_plain(boundary.attrs), ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError, OverflowError) as exc:
            raise PlanValidationError(
                "semantic boundary attrs must be JSON-compatible",
                code="semantic_boundary.attrs",
                path=f"{path}.attrs",
            ) from exc
    previous_segment_end = 0
    for segment in plan.segments:
        if not (0 <= segment.spoken_start <= segment.spoken_end <= len(text)):
            raise PlanValidationError(
                "segment range is outside spoken text", code="segment.out_of_range"
            )
        if segment.text != text[segment.spoken_start : segment.spoken_end]:
            raise PlanValidationError(
                "segment text does not match spoken range", code="segment.range_mismatch"
            )
        if segment.spoken_start < previous_segment_end:
            raise PlanValidationError("segments are not sorted", code="segment.order")
        previous_segment_end = segment.spoken_end
        for pause in (segment.pause_before, segment.pause_after):
            if pause is not None and not isinstance(pause, (PauseIntent, LegacyPause)):
                raise PlanValidationError("pause must be semantic intent", code="pause.invalid")
    for event in plan.boundaries:
        if not (0 <= event.position <= len(text)):
            raise PlanValidationError(
                "boundary position is outside spoken text", code="boundary.out_of_range"
            )
    for annotation in plan.annotations:
        if not (
            0
            <= annotation.structural_start
            <= annotation.structural_end
            <= len(plan.texts.structural)
        ):
            raise PlanValidationError(
                "annotation structural range is outside structural text",
                code="annotation.structural_range",
            )
        if (annotation.spoken_start is None) != (annotation.spoken_end is None):
            raise PlanValidationError(
                "annotation spoken range must be both null or both present",
                code="annotation.spoken_range",
            )
        if (
            annotation.spoken_start is not None
            and annotation.spoken_end is not None
            and not (0 <= annotation.spoken_start <= annotation.spoken_end <= len(text))
        ):
            raise PlanValidationError(
                "annotation spoken range is outside spoken text", code="annotation.spoken_range"
            )
    language_runs = {run.id: run for run in plan.languages}
    for run in plan.languages:
        if not (0 <= run.spoken_start <= run.spoken_end <= len(text)):
            raise PlanValidationError(
                "language range is outside spoken text", code="language.out_of_range"
            )
    previous_token_key: tuple[int, int] | None = None
    for token in plan.tokens:
        if not (0 <= token.spoken_start <= token.spoken_end <= len(text)):
            raise PlanValidationError(
                "token range is outside spoken text", code="token.out_of_range"
            )
        if token.text != text[token.spoken_start : token.spoken_end]:
            raise PlanValidationError(
                "token text does not match spoken range", code="token.range_mismatch"
            )
        token_key = (token.spoken_start, token.spoken_end)
        if previous_token_key is not None and token_key < previous_token_key:
            raise PlanValidationError("tokens are not sorted", code="token.order")
        previous_token_key = token_key
        for field_name in ("pos", "tag", "lemma", "language", "morph"):
            value = getattr(token, field_name)
            if value is not None and not isinstance(value, str):
                raise PlanValidationError(
                    f"token {field_name} must be a string", code="token.field_type"
                )
    seen_run_ids: set[str] = set()
    previous_run_end = 0
    for linguistic_run in plan.linguistic_runs:
        if linguistic_run.language_run_id in seen_run_ids:
            raise PlanValidationError(
                f"duplicate linguistic run {linguistic_run.language_run_id}",
                code="linguistic_run.duplicate",
            )
        seen_run_ids.add(linguistic_run.language_run_id)
        language_run = language_runs.get(linguistic_run.language_run_id)
        if language_run is None:
            raise PlanValidationError(
                "linguistic run references unknown language run",
                code="linguistic_run.unknown_language",
            )
        if linguistic_run.provider not in {"spacy", "fallback", "unknown"}:
            raise PlanValidationError(
                "linguistic run provider is invalid", code="linguistic_run.provider"
            )
        if not (0 <= linguistic_run.token_start <= linguistic_run.token_end <= len(plan.tokens)):
            raise PlanValidationError(
                "linguistic run token range is invalid", code="linguistic_run.token_range"
            )
        if linguistic_run.token_start < previous_run_end:
            raise PlanValidationError(
                "linguistic runs overlap or are not ordered", code="linguistic_run.order"
            )
        previous_run_end = linguistic_run.token_end
        if linguistic_run.provider == "fallback" and linguistic_run.model is not None:
            raise PlanValidationError(
                "fallback linguistic run cannot claim a model",
                code="linguistic_run.model",
            )
        for field_name in ("model", "provider_version", "model_version"):
            value = getattr(linguistic_run, field_name)
            if value is not None and not isinstance(value, str):
                raise PlanValidationError(
                    f"linguistic run {field_name} must be a string",
                    code="linguistic_run.field_type",
                )
        for token in plan.tokens[linguistic_run.token_start : linguistic_run.token_end]:
            if not (
                language_run.spoken_start <= token.spoken_start
                and token.spoken_end <= language_run.spoken_end
            ):
                raise PlanValidationError(
                    "linguistic run tokens are outside language range",
                    code="linguistic_run.token_membership",
                )
    segment_ids = {segment.id for segment in plan.segments}
    annotation_ids = {annotation.id for annotation in plan.annotations}
    token_count = len(plan.tokens)
    for segment in plan.segments:
        if any(index < 0 or index >= token_count for index in segment.token_indices):
            raise PlanValidationError(
                "segment references unknown token", code="segment.unknown_token"
            )
        if len(segment.token_indices) != len(set(segment.token_indices)):
            raise PlanValidationError(
                "segment references a token more than once", code="segment.token_membership"
            )
        if any(
            not (
                plan.tokens[index].spoken_start < segment.spoken_end
                and plan.tokens[index].spoken_end > segment.spoken_start
            )
            for index in segment.token_indices
        ):
            raise PlanValidationError(
                "segment token is outside segment range", code="segment.token_membership"
            )
        if any(annotation_id not in annotation_ids for annotation_id in segment.annotation_ids):
            raise PlanValidationError(
                "segment references unknown annotation", code="segment.unknown_annotation"
            )
    marker_ids = {marker.id for marker in plan.markers}
    for marker in plan.markers:
        if not (0 <= marker.spoken_position <= len(text)):
            raise PlanValidationError(
                "marker position is outside spoken text", code="marker.out_of_range"
            )
    previous_unit_end = 0
    for expected_index, unit in enumerate(plan.units):
        if unit.index != expected_index:
            raise PlanValidationError("units must have contiguous indexes", code="unit.index")
        if unit.spoken_start < previous_unit_end:
            raise PlanValidationError("units must not overlap", code="unit.overlap")
        previous_unit_end = unit.spoken_end
    segment_by_id = {segment.id: segment for segment in plan.segments}
    for unit in plan.units:
        if not all(segment_id in segment_ids for segment_id in unit.segment_ids):
            raise PlanValidationError(
                "unit references unknown segment", code="unit.unknown_segment"
            )
        if not all(marker_id in marker_ids for marker_id in unit.marker_ids):
            raise PlanValidationError("unit references unknown marker", code="unit.unknown_marker")
        if not (0 <= unit.spoken_start <= unit.spoken_end <= len(text)):
            raise PlanValidationError("unit range is outside spoken text", code="unit.out_of_range")
        if unit.content_hash_schema != UNIT_HASH_SCHEMA:
            raise PlanValidationError(
                "unsupported unit content hash schema", code="unit.hash_schema"
            )
        unit_segments = [segment_by_id[segment_id] for segment_id in unit.segment_ids]
        marker_values = tuple(marker for marker in plan.markers if marker.id in unit.marker_ids)
        if unit.content_hash != semantic_hash(
            unit_hash_payload(
                _HashUnit(
                    unit_segments,
                    unit.marker_ids,
                    marker_values,
                    plan.tokens,
                    plan.semantic_boundaries,
                    unit.spoken_start,
                    unit.spoken_end,
                )
            )
        ):
            raise PlanValidationError(
                "unit content hash does not match semantics", code="unit.hash_mismatch"
            )
        if unit_segments and (
            unit.spoken_start > unit_segments[0].spoken_start
            or unit.spoken_end < unit_segments[-1].spoken_end
        ):
            raise PlanValidationError("unit range does not contain its segments", code="unit.range")
    flattened_segment_ids = [segment_id for unit in plan.units for segment_id in unit.segment_ids]
    expected_segment_ids = [segment.id for segment in plan.segments]
    if flattened_segment_ids != expected_segment_ids:
        raise PlanValidationError(
            "units must contain every segment exactly once in global order",
            code="unit.segment_membership",
        )
    assigned_markers = [marker_id for unit in plan.units for marker_id in unit.marker_ids]
    if len(assigned_markers) != len(set(assigned_markers)):
        raise PlanValidationError(
            "marker belongs to more than one unit", code="marker.unit_membership"
        )
    if set(assigned_markers) != marker_ids:
        raise PlanValidationError(
            "every marker must belong to exactly one unit", code="marker.unit_membership"
        )


def validate_plan(plan: UtterancePlan) -> None:
    """Validate a canonical plan, including its identity and renderability."""
    validate_plan_structure(plan)
    if not plan.plan_id:
        raise PlanValidationError("plan_id is required", code="plan_id.required")
    if plan.plan_id != semantic_hash(plan.semantic_dict()):
        raise PlanValidationError(
            "plan_id does not match semantic contents", code="plan_id.mismatch"
        )
    from .renderability import assert_renderable

    assert_renderable(plan)


class _HashUnit:
    def __init__(
        self,
        segments: list[PlanSegment],
        marker_ids: tuple[str, ...],
        marker_values: tuple[Marker, ...],
        tokens: tuple[TokenAnnotation, ...],
        semantic_boundaries: tuple[SemanticBoundary, ...],
        spoken_start: int,
        spoken_end: int,
    ) -> None:
        self.segments = segments
        self.marker_ids = marker_ids
        self.marker_values = marker_values
        self.tokens = tokens
        self.semantic_boundaries = semantic_boundaries
        self.spoken_start = spoken_start
        self.spoken_end = spoken_end


@dataclass(frozen=True, slots=True)
class LegacyPause:
    """Frozen schema-v4 pause payload retained only by the historical model reader."""

    seconds: int | float
    events: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            type(self.seconds) not in {int, float}
            or not math.isfinite(self.seconds)
            or self.seconds < 0
        ):
            raise ValueError("legacy pause seconds must be finite and non-negative")
        if not isinstance(self.events, tuple) or any(
            not isinstance(item, str) for item in self.events
        ):
            raise ValueError("legacy pause events must be a tuple of strings")

    def to_dict(self) -> dict[str, Any]:
        return {"seconds": self.seconds, "events": list(self.events)}


PauseType = Literal[
    "none",
    "x-weak",
    "weak",
    "medium",
    "strong",
    "x-strong",
    "timed",
    "clause",
    "sentence",
    "paragraph",
    "parenthetical",
    "voice_change",
]


@dataclass(frozen=True, slots=True)
class PauseIntent:
    """A pause instruction, without renderer-selected timing."""

    type: PauseType
    time: str | None = None

    def __post_init__(self) -> None:
        allowed = {
            "none",
            "x-weak",
            "weak",
            "medium",
            "strong",
            "x-strong",
            "timed",
            "clause",
            "sentence",
            "paragraph",
            "parenthetical",
            "voice_change",
        }
        if not isinstance(self.type, str) or self.type not in allowed:
            raise ValueError(f"unsupported pause intent: {self.type!r}")
        if self.type == "timed":
            if not isinstance(self.time, str) or not self.time.strip():
                raise ValueError("timed pause requires time")
        elif self.time is not None:
            raise ValueError("time is only valid for type='timed'")

    def to_dict(self) -> str | dict[str, str]:
        if self.type == "timed":
            return {"type": "timed", "time": cast(str, self.time)}
        return self.type


@dataclass(frozen=True, slots=True)
class TokenView:
    """Linguistic facts for one token, with a segment-local character span."""

    start: int
    end: int
    lemma: str | None = None
    pos: str | None = None
    tag: str | None = None
    morph: str | None = None

    def __post_init__(self) -> None:
        if type(self.start) is not int or type(self.end) is not int:
            raise ValueError("token span coordinates must be integers")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("token span must be non-empty and non-negative")
        for field_name in ("lemma", "pos", "tag", "morph"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"token {field_name} must be a string or None")

    def surface(self, text: str) -> str:
        """Derive token surface from its owning segment text."""
        if self.end > len(text):
            raise ValueError("token span is outside segment text")
        return text[self.start : self.end]

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in (
                ("start", self.start),
                ("end", self.end),
                ("lemma", self.lemma),
                ("pos", self.pos),
                ("tag", self.tag),
                ("morph", self.morph),
            )
            if value is not None
        }


@dataclass(frozen=True, slots=True)
class FlowSegment:
    """One atomic renderer operation in the ordered executable flow."""

    text: str
    language: str
    pause_before: PauseIntent | None = None
    pause_after: PauseIntent | None = None
    directives: SegmentDirectives = field(default_factory=SegmentDirectives)
    tokens: tuple[TokenView, ...] = ()
    markers: tuple[str, ...] = ()
    heading: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise ValueError("segment text must be a string")
        if not isinstance(self.language, str) or not self.language:
            raise ValueError("segment language must be a non-empty string")
        if not isinstance(self.directives, SegmentDirectives):
            raise ValueError("segment directives must be SegmentDirectives")
        if not isinstance(self.tokens, tuple) or any(
            not isinstance(token, TokenView) for token in self.tokens
        ):
            raise ValueError("segment tokens must be a tuple of TokenView values")
        if not isinstance(self.markers, tuple):
            raise ValueError("segment markers must be a tuple")
        if self.pause_before is not None and not isinstance(self.pause_before, PauseIntent):
            raise ValueError("pause_before must be a PauseIntent or None")
        if self.pause_after is not None and not isinstance(self.pause_after, PauseIntent):
            raise ValueError("pause_after must be a PauseIntent or None")
        if any(not isinstance(marker, str) or not marker for marker in self.markers):
            raise ValueError("segment markers must be non-empty strings")
        previous_end = 0
        for index, token in enumerate(self.tokens):
            if token.end > len(self.text):
                raise ValueError(f"token {index} span is outside segment text")
            if token.start < previous_end:
                raise ValueError("token spans must be ordered and non-overlapping")
            previous_end = token.end
        if self.heading is not None and (type(self.heading) is not int or self.heading < 1):
            raise ValueError("heading must be a positive integer")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "text": self.text,
            "language": self.language,
            "directives": self.directives.to_dict(),
            "tokens": [token.to_dict() for token in self.tokens],
            "markers": list(self.markers),
        }
        if self.pause_before is not None:
            result["pause_before"] = self.pause_before.to_dict()
        if self.pause_after is not None:
            result["pause_after"] = self.pause_after.to_dict()
        if self.heading is not None:
            result["heading"] = self.heading
        return result


@dataclass(frozen=True, slots=True)
class FlowUnit:
    """A render/cache unit containing ordered atomic renderer segments."""

    segments: tuple[FlowSegment, ...]
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.segments, tuple) or any(
            not isinstance(segment, FlowSegment) for segment in self.segments
        ):
            raise PlanValidationError(
                "flow unit segments must be a tuple of FlowSegment values", code="flow.segments"
            )
        expected = flow_unit_hash(self.segments)
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected)
        elif not isinstance(self.content_hash, str) or self.content_hash != expected:
            raise PlanValidationError(
                "flow unit hash does not match local semantics", code="flow.hash"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "segments": [segment.to_dict() for segment in self.segments],
            "hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class DocumentInfo:
    """Small portable document metadata retained for downstream consumers."""

    format: str | None = None
    ssmd_version: str | None = None
    title: str | None = None
    semantics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("format", "ssmd_version", "title"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"document {name} must be a string or None")
        if not isinstance(self.semantics, Mapping):
            raise ValueError("document semantics must be a mapping")
        object.__setattr__(self, "semantics", _plain(self.semantics))

    def to_dict(self) -> dict[str, Any]:
        result = {"semantics": _plain(self.semantics)}
        for key in ("format", "ssmd_version", "title"):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        return result


@dataclass(frozen=True, slots=True)
class LinguisticProvenance:
    """Document/language-level provider provenance, not provider runtime state."""

    language: str
    provider: Literal["spacy", "fallback", "unknown"]
    model: str | None = None
    provider_version: str | None = None
    model_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.language, str) or not self.language:
            raise ValueError("linguistic provenance language must be non-empty")
        if not isinstance(self.provider, str) or self.provider not in {
            "spacy",
            "fallback",
            "unknown",
        }:
            raise ValueError("linguistic provenance provider is unsupported")
        for name in ("model", "provider_version", "model_version"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"linguistic provenance {name} must be a string or None")

    def to_dict(self) -> dict[str, str]:
        return {
            key: value
            for key, value in (
                ("language", self.language),
                ("provider", self.provider),
                ("model", self.model),
                ("provider_version", self.provider_version),
                ("model_version", self.model_version),
            )
            if value is not None
        }


@dataclass(frozen=True, slots=True)
class FlowPlan:
    """Compact v5 renderer-facing plan model, independent of compiler lookup tables."""

    language: str
    unit: Literal["sentence", "paragraph"]
    flow: tuple[FlowUnit, ...]
    document: DocumentInfo = field(default_factory=DocumentInfo)
    linguistics: tuple[LinguisticProvenance, ...] = ()
    plan_id: str = ""
    producer: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    format: str = FORMAT
    schema_version: int = 5
    hash_schema: str = "utterplan-flow-v1"

    def __post_init__(self) -> None:
        if self.format != FORMAT:
            raise PlanValidationError("format must be 'utterplan'", code="format.invalid")
        if type(self.schema_version) is not int or self.schema_version != 5:
            raise PlanValidationError("FlowPlan requires schema version 5", code="schema.version")
        if not isinstance(self.language, str) or not self.language:
            raise PlanValidationError(
                "language must be a non-empty string", code="language.invalid"
            )
        if not isinstance(self.unit, str) or self.unit not in {"sentence", "paragraph"}:
            raise PlanValidationError("unit must be sentence or paragraph", code="unit.invalid")
        if self.hash_schema != FLOW_HASH_SCHEMA:
            raise PlanValidationError("unsupported flow hash schema", code="flow.hash_schema")
        if not isinstance(self.document, DocumentInfo):
            raise PlanValidationError("document must be DocumentInfo", code="document.type")
        if not isinstance(self.flow, tuple):
            raise PlanValidationError("flow must be a tuple", code="flow.type")
        if not isinstance(self.linguistics, tuple):
            raise PlanValidationError("linguistics must be a tuple", code="linguistics.type")
        if not isinstance(self.warnings, tuple):
            raise PlanValidationError("warnings must be a tuple", code="warnings.type")
        if any(not isinstance(item, FlowUnit) for item in self.flow):
            raise PlanValidationError("flow must contain FlowUnit values", code="flow.type")
        if any(not isinstance(item, LinguisticProvenance) for item in self.linguistics):
            raise PlanValidationError(
                "linguistics must contain provenance records", code="linguistics.type"
            )
        if not isinstance(self.producer, Mapping):
            raise PlanValidationError("producer must be a mapping", code="producer.type")
        object.__setattr__(self, "producer", _plain(self.producer))
        if not isinstance(self.plan_id, str):
            raise PlanValidationError("plan_id must be a string", code="plan.identity")
        if any(not isinstance(item, str) for item in self.warnings):
            raise PlanValidationError("warnings must be strings", code="warnings.type")
        try:
            expected = flow_plan_id(self.to_dict())
        except (TypeError, ValueError) as exc:
            raise PlanValidationError(
                "plan contains values outside the semantic data model", code="plan.identity"
            ) from exc
        if not self.plan_id:
            object.__setattr__(self, "plan_id", expected)
        elif self.plan_id != expected:
            raise PlanValidationError(
                "plan ID does not match executable semantics", code="plan.identity"
            )

    def to_dict(self) -> dict[str, Any]:
        """Return the v5 semantic consumer model, with no compiler graph."""
        result: dict[str, Any] = {
            "format": self.format,
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "language": self.language,
            "unit": self.unit,
            "hash_schema": self.hash_schema,
            "flow": [unit.to_dict() for unit in self.flow],
            "document": self.document.to_dict(),
            "linguistics": [item.to_dict() for item in self.linguistics],
        }
        if self.producer:
            result["producer"] = _plain(self.producer)
        if self.warnings:
            result["warnings"] = list(self.warnings)
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FlowPlan:
        if not isinstance(data, Mapping):
            raise PlanFormatError("v5 plan must be an object", code="plan.type")
        allowed_root = {
            "format",
            "schema_version",
            "plan_id",
            "language",
            "unit",
            "hash_schema",
            "flow",
            "document",
            "linguistics",
            "producer",
            "warnings",
        }
        unknown = set(data) - allowed_root
        if unknown:
            raise PlanFormatError(
                f"unknown v5 plan fields: {sorted(unknown)}", code="field.unknown"
            )
        required = {
            "format",
            "schema_version",
            "plan_id",
            "language",
            "unit",
            "hash_schema",
            "flow",
        }
        missing = required - set(data)
        if missing:
            raise PlanFormatError(
                f"required v5 fields are missing: {sorted(missing)}", code="field.required"
            )
        if (
            data.get("format") != FORMAT
            or type(data.get("schema_version")) is not int
            or data.get("schema_version") != 5
        ):
            raise PlanFormatError("expected schema-v5 UtterPlan", code="schema.version")
        language = data.get("language")
        if not isinstance(language, str) or not language:
            raise PlanFormatError("language must be a non-empty string", code="language.invalid")
        unit_value = data.get("unit")
        if not isinstance(unit_value, str) or unit_value not in {"sentence", "paragraph"}:
            raise PlanFormatError("unit must be sentence or paragraph", code="unit.invalid")
        unit = cast(Literal["sentence", "paragraph"], unit_value)
        flow_value = data.get("flow")
        if not isinstance(flow_value, (list, tuple)):
            raise PlanFormatError("flow must be an array", code="flow.type")
        flow: list[FlowUnit] = []
        for unit_index, raw_unit in enumerate(flow_value):
            unit_path = f"$.flow[{unit_index}]"
            if not isinstance(raw_unit, Mapping):
                raise PlanFormatError(
                    "flow unit must be an object", code="flow.unit", path=unit_path
                )
            if set(raw_unit) - {"segments", "hash"}:
                raise PlanFormatError(
                    "unknown flow unit fields", code="field.unknown", path=unit_path
                )
            raw_segments = raw_unit.get("segments")
            if not isinstance(raw_segments, (list, tuple)):
                raise PlanFormatError(
                    "flow unit segments must be an array", code="flow.segments", path=unit_path
                )
            segments: list[FlowSegment] = []
            for segment_index, raw_segment in enumerate(raw_segments):
                segment_path = f"{unit_path}.segments[{segment_index}]"
                if not isinstance(raw_segment, Mapping):
                    raise PlanFormatError(
                        "flow segment must be an object", code="flow.segment", path=segment_path
                    )
                allowed_segment = {
                    "text",
                    "language",
                    "pause_before",
                    "pause_after",
                    "directives",
                    "tokens",
                    "markers",
                    "heading",
                }
                unknown_segment = set(raw_segment) - allowed_segment
                if unknown_segment:
                    raise PlanFormatError(
                        f"unknown flow segment fields: {sorted(unknown_segment)}",
                        code="field.unknown",
                        path=segment_path,
                    )
                text = raw_segment.get("text")
                segment_language = raw_segment.get("language", language)
                directives = raw_segment.get("directives", {})
                if not isinstance(text, str):
                    raise PlanFormatError(
                        "segment text must be a string", code="segment.text", path=segment_path
                    )
                if not isinstance(segment_language, str) or not segment_language:
                    raise PlanFormatError(
                        "segment language must be non-empty",
                        code="segment.language",
                        path=segment_path,
                    )
                if not isinstance(directives, Mapping):
                    raise PlanFormatError(
                        "segment directives must be an object",
                        code="segment.directives",
                        path=segment_path,
                    )
                try:
                    parsed_directives = _directive(directives)
                    raw_tokens = raw_segment.get("tokens", [])
                    if not isinstance(raw_tokens, (list, tuple)):
                        raise PlanFormatError(
                            "segment tokens must be an array", code="token.type", path=segment_path
                        )
                    tokens: list[TokenView] = []
                    for token_index, raw_token in enumerate(raw_tokens):
                        token_path = f"{segment_path}.tokens[{token_index}]"
                        if not isinstance(raw_token, Mapping):
                            raise PlanFormatError(
                                "token must be an object", code="token.type", path=token_path
                            )
                        if set(raw_token) - {"start", "end", "lemma", "pos", "tag", "morph"}:
                            raise PlanFormatError(
                                "unknown token fields", code="field.unknown", path=token_path
                            )
                        tokens.append(
                            TokenView(
                                _expect(raw_token.get("start"), int, f"{token_path}.start"),
                                _expect(raw_token.get("end"), int, f"{token_path}.end"),
                                raw_token.get("lemma"),
                                raw_token.get("pos"),
                                raw_token.get("tag"),
                                raw_token.get("morph"),
                            )
                        )
                    raw_markers = raw_segment.get("markers", [])
                    if not isinstance(raw_markers, (list, tuple)) or any(
                        not isinstance(marker, str) or not marker for marker in raw_markers
                    ):
                        raise PlanFormatError(
                            "markers must be non-empty strings",
                            code="segment.markers",
                            path=segment_path,
                        )
                    pause_before = _pause(raw_segment.get("pause_before"))
                    pause_after = _pause(raw_segment.get("pause_after"))
                    segments.append(
                        FlowSegment(
                            text=text,
                            language=segment_language,
                            pause_before=pause_before,
                            pause_after=pause_after,
                            directives=parsed_directives,
                            tokens=tuple(tokens),
                            markers=tuple(raw_markers),
                            heading=raw_segment.get("heading"),
                        )
                    )
                except PlanFormatError:
                    raise
                except (TypeError, ValueError, KeyError, IndexError) as exc:
                    raise PlanFormatError(str(exc), code="flow.segment", path=segment_path) from exc
            unit_hash = raw_unit.get("hash")
            if not isinstance(unit_hash, str):
                raise PlanFormatError(
                    "flow unit hash must be a string", code="flow.hash", path=unit_path
                )
            flow.append(FlowUnit(tuple(segments), unit_hash))

        document_value = data.get("document", {})
        if not isinstance(document_value, Mapping):
            raise PlanFormatError("document must be an object", code="document.type")
        if set(document_value) - {"format", "ssmd_version", "title", "semantics"}:
            raise PlanFormatError(
                "unknown document fields", code="field.unknown", path="$.document"
            )
        semantics = document_value.get("semantics", {})
        if not isinstance(semantics, Mapping):
            raise PlanFormatError("document semantics must be an object", code="document.semantics")
        try:
            document = DocumentInfo(
                format=document_value.get("format"),
                ssmd_version=document_value.get("ssmd_version"),
                title=document_value.get("title"),
                semantics=_plain(semantics),
            )
        except ValueError as exc:
            raise PlanFormatError(str(exc), code="document.invalid", path="$.document") from exc

        raw_linguistics = data.get("linguistics", [])
        if not isinstance(raw_linguistics, (list, tuple)):
            raise PlanFormatError("linguistics must be an array", code="linguistics.type")
        linguistics: list[LinguisticProvenance] = []
        for index, value in enumerate(raw_linguistics):
            path = f"$.linguistics[{index}]"
            if not isinstance(value, Mapping):
                raise PlanFormatError(
                    "linguistic provenance must be an object", code="linguistics.record", path=path
                )
            if set(value) - {"language", "provider", "model", "provider_version", "model_version"}:
                raise PlanFormatError(
                    "unknown linguistic provenance fields", code="field.unknown", path=path
                )
            linguistic_language = value.get("language")
            linguistic_provider = value.get("provider")
            if not isinstance(linguistic_language, str) or not isinstance(linguistic_provider, str):
                raise PlanFormatError(
                    "linguistic provenance requires language and provider strings",
                    code="linguistics.record",
                    path=path,
                )
            try:
                linguistics.append(
                    LinguisticProvenance(
                        language=linguistic_language,
                        provider=cast(Literal["spacy", "fallback", "unknown"], linguistic_provider),
                        model=value.get("model"),
                        provider_version=value.get("provider_version"),
                        model_version=value.get("model_version"),
                    )
                )
            except (TypeError, ValueError) as exc:
                raise PlanFormatError(str(exc), code="linguistics.record", path=path) from exc

        producer = data.get("producer", {})
        warnings = data.get("warnings", [])
        if not isinstance(producer, Mapping):
            raise PlanFormatError("producer must be an object", code="producer.type")
        if not isinstance(warnings, (list, tuple)) or any(
            not isinstance(item, str) for item in warnings
        ):
            raise PlanFormatError("warnings must be strings", code="warnings.type")
        return cls(
            language=language,
            unit=unit,
            flow=tuple(flow),
            document=document,
            linguistics=tuple(linguistics),
            plan_id=data.get("plan_id", ""),
            producer=dict(producer),
            warnings=tuple(warnings),
            format=data.get("format", FORMAT),
            schema_version=data.get("schema_version", 5),
            hash_schema=data.get("hash_schema", FLOW_HASH_SCHEMA),
        )

    def validate(self) -> None:
        """Recheck content hashes and semantic identity for callers loading mutable mappings."""
        for unit in self.flow:
            if unit.content_hash != flow_unit_hash(unit.segments):
                raise PlanValidationError(
                    "flow unit hash does not match local semantics", code="flow.hash"
                )
        if self.plan_id != flow_plan_id(self.to_dict()):
            raise PlanValidationError(
                "plan ID does not match executable semantics", code="plan.identity"
            )

    def to_toml(self) -> str:
        from .toml_codec import dumps_toml

        return dumps_toml(self)

    @classmethod
    def from_toml(cls, value: str) -> FlowPlan:
        from .toml_codec import loads_toml

        result = loads_toml(value)
        if not isinstance(result, cls):
            raise PlanFormatError("TOML did not decode to a v5 FlowPlan", code="schema.version")
        return result

    @classmethod
    def load(cls, path: str | Path) -> FlowPlan:
        """Load a semantic plan from a TOML file; JSON is a migration input only."""
        source = Path(path)
        if source.suffix.lower() == ".json":
            raise PlanFormatError(
                "JSON is not a supported plan-file format", code="format.unsupported_json"
            )
        return cls.from_toml(source.read_text(encoding="utf-8"))

    def save(self, path: str | Path, *, create_parent: bool = False) -> None:
        """Write the canonical TOML plan, optionally creating parent directories."""
        from .atomic_io import atomic_write_text

        atomic_write_text(path, self.to_toml(), create_parent=create_parent)
