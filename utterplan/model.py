from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from ._version import __version__
from .config import semantic_config
from .exceptions import PlanFormatError, PlanValidationError, UnsupportedSchemaError
from .hashing import UNIT_HASH_SCHEMA, semantic_hash, unit_hash_payload
from .language import LanguageRun
from .migration import migrate_plan_data
from .versioning import FORMAT, SCHEMA_VERSION


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
    seconds: float | None = None
    origin: str = "planner"
    strength: str | None = None
    attrs: Mapping[str, Any] = field(default_factory=dict)

    @property
    def pos(self) -> int:
        return self.position

    @property
    def duration_s(self) -> float | None:
        return self.seconds

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
class ResolvedPause:
    seconds: float = 0.0
    events: tuple[str, ...] = ()

    @property
    def duration_s(self) -> float:
        return self.seconds

    def to_dict(self) -> dict[str, Any]:
        return {"seconds": self.seconds, "events": list(self.events)}


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
    pause_before: ResolvedPause = field(default_factory=ResolvedPause)
    pause_after: ResolvedPause = field(default_factory=ResolvedPause)
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
            "pause_before": self.pause_before.to_dict(),
            "pause_after": self.pause_after.to_dict(),
            "directives": self.directives.to_dict(),
            "token_indices": list(self.token_indices),
            "annotation_ids": list(self.annotation_ids),
        }
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
    schema_version: int = SCHEMA_VERSION

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
            "boundaries": [_plain(x) for x in self.boundaries],
            "tokens": [_plain(x) for x in self.tokens],
            "segments": [_plain(x) for x in self.segments],
            "units": [_plain(x) for x in self.units],
            "markers": [_plain(x) for x in self.markers],
            "document_metadata": _plain(self.document_metadata),
            "warnings": list(self.warnings),
            "diagnostics": [_plain(x) for x in self.diagnostics],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return (
            __import__("json").dumps(
                self.to_dict(), ensure_ascii=False, sort_keys=True, indent=indent, allow_nan=False
            )
            + "\n"
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def from_json(cls, value: str) -> UtterancePlan:
        import json

        try:
            data = json.loads(value)
        except json.JSONDecodeError as exc:
            raise PlanFormatError(str(exc), code="json.invalid") from exc
        return cls.from_dict(data)

    @classmethod
    def load(cls, path: str | Path) -> UtterancePlan:
        return cls.from_json(Path(path).read_text(encoding="utf-8"))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> UtterancePlan:
        migrated = migrate_plan_data(data)
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
    if data.get("schema_version") != SCHEMA_VERSION:
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
        "boundaries",
        "tokens",
        "linguistic_runs",
        "segments",
        "units",
        "markers",
        "warnings",
        "diagnostics",
    ):
        _expect(data.get(key), list, f"$.{key}")
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


def _pause(data: Mapping[str, Any] | None) -> ResolvedPause:
    data = data or {}
    return ResolvedPause(float(data.get("seconds", 0.0)), tuple(data.get("events", ())))


def _directive(data: Mapping[str, Any] | None) -> SegmentDirectives:
    data = data or {}
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
        boundaries=tuple(
            BoundaryEvent(
                str(x["id"]),
                int(x.get("position", x.get("pos", 0))),
                str(x["kind"]),
                x.get("seconds", x.get("duration_s")),
                str(x.get("origin", "planner")),
                x.get("strength"),
                dict(x.get("attrs", {})),
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
                _pause(x.get("pause_before")),
                _pause(x.get("pause_after")),
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


def validate_plan(plan: UtterancePlan) -> None:
    text = plan.texts.spoken
    if plan.source.format not in {"plain", "ssmd"}:
        raise PlanValidationError("unsupported source format", code="source.format")
    if plan.source.text is None:
        raise PlanValidationError("source text is required", code="source.text")
    if not plan.plan_id:
        raise PlanValidationError("plan_id is required", code="plan_id.required")
    ids: set[str] = set()
    for collection, _name in (
        (plan.languages, "language"),
        (plan.annotations, "annotation"),
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
    boundary_ids = {event.id for event in plan.boundaries}
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
            if not math.isfinite(pause.seconds) or pause.seconds < 0:
                raise PlanValidationError(
                    "pause must be finite and non-negative", code="pause.invalid"
                )
            for event_id in pause.events:
                if event_id not in boundary_ids:
                    raise PlanValidationError(
                        f"unknown boundary {event_id}", code="pause.unknown_boundary"
                    )
    for boundary in plan.boundaries:
        if not (0 <= boundary.position <= len(text)):
            raise PlanValidationError(
                "boundary position is outside spoken text", code="boundary.out_of_range"
            )
        if boundary.seconds is not None and (
            not math.isfinite(float(boundary.seconds)) or float(boundary.seconds) < 0
        ):
            raise PlanValidationError(
                "boundary seconds must be finite and non-negative", code="boundary.seconds"
            )
    annotation_ids = {annotation.id for annotation in plan.annotations}
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
            unit_hash_payload(_HashUnit(unit_segments, unit.marker_ids, marker_values, plan.tokens))
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
    if plan.plan_id != semantic_hash(plan.semantic_dict()):
        raise PlanValidationError(
            "plan_id does not match semantic contents", code="plan_id.mismatch"
        )


class _HashUnit:
    def __init__(
        self,
        segments: list[PlanSegment],
        marker_ids: tuple[str, ...],
        marker_values: tuple[Marker, ...],
        tokens: tuple[TokenAnnotation, ...],
    ) -> None:
        self.segments = segments
        self.marker_ids = marker_ids
        self.marker_values = marker_values
        self.tokens = tokens
