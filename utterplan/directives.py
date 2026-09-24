from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from .model import (
    AnnotationSpan,
    AudioDirective,
    EmphasisDirective,
    ExtensionDirective,
    PlanSegment,
    PronunciationDirective,
    ProsodyDirective,
    SayAsDirective,
    SegmentDirectives,
    SubstitutionDirective,
    VoiceDirective,
)


def resolve_directives(
    segment: PlanSegment,
    annotations: tuple[AnnotationSpan, ...],
    *,
    voice_defaults: Mapping[str, Any] | None = None,
) -> PlanSegment:
    selected = sorted(
        (
            annotation
            for annotation in annotations
            if annotation.spoken_start is not None
            and annotation.spoken_end is not None
            and annotation.spoken_start <= segment.spoken_start
            and segment.spoken_end <= annotation.spoken_end
        ),
        key=lambda annotation: (
            annotation.spoken_start or 0,
            -(annotation.spoken_end or 0),
            annotation.id,
        ),
    )

    voice: VoiceDirective | None = None
    pronunciation: PronunciationDirective | None = None
    emphasis: EmphasisDirective | None = None
    say_as: SayAsDirective | None = None
    substitution: SubstitutionDirective | None = None
    audio: AudioDirective | None = None
    extensions: list[ExtensionDirective] = []
    block_prosody: list[dict[str, str]] = []
    inline_prosody: list[dict[str, str]] = []

    for annotation in selected:
        attrs = annotation.attrs
        tag = _semantic_tag(annotation)
        is_block = annotation.kind == "directive"

        if tag == "voice":
            voice_candidate = _voice(attrs)
            if voice_candidate is not None:
                voice = voice_candidate
        elif tag in {"phoneme", "pronunciation"}:
            pronunciation_candidate = _pronunciation(attrs)
            if pronunciation_candidate is not None:
                pronunciation = pronunciation_candidate
        elif tag == "emphasis":
            level = _first(attrs, "emphasis", "level")
            if level is not None:
                emphasis = EmphasisDirective(level)
        elif tag == "say-as":
            interpret_as = _first(attrs, "as")
            if interpret_as is not None:
                say_as = SayAsDirective(
                    interpret_as,
                    _first(attrs, "format"),
                    _first(attrs, "detail"),
                )
        elif tag == "sub":
            alias = _first(attrs, "sub")
            if alias is not None:
                substitution = SubstitutionDirective(alias)
        elif tag == "audio":
            audio_candidate = _audio(attrs)
            if audio_candidate is not None:
                audio = audio_candidate
        elif tag == "extension":
            extension_candidate = _extension(attrs)
            if extension_candidate is not None:
                extensions.append(extension_candidate)

        fields = _prosody_fields(attrs, tag)
        if fields:
            (block_prosody if is_block else inline_prosody).append(fields)

    prosody_values: dict[str, str] = {}
    if voice is not None and voice.reference is not None and voice_defaults is not None:
        defaults = voice_defaults.get(voice.reference)
        if isinstance(defaults, Mapping):
            prosody_values.update(_prosody_fields(defaults, "prosody"))
    for contribution in block_prosody:
        prosody_values.update(contribution)
    for contribution in inline_prosody:
        prosody_values.update(contribution)
    prosody = ProsodyDirective(**prosody_values) if prosody_values else None

    return replace(
        segment,
        directives=SegmentDirectives(
            voice=voice,
            pronunciation=pronunciation,
            prosody=prosody,
            emphasis=emphasis,
            say_as=say_as,
            substitution=substitution,
            audio=audio,
            extensions=tuple(extensions),
        ),
    )


def _semantic_tag(annotation: AnnotationSpan) -> str:
    return str(annotation.attrs.get("tag") or annotation.kind).lower().replace("_", "-")


def _voice(attrs: Mapping[str, Any]) -> VoiceDirective | None:
    values: dict[str, Any] = {
        "reference": _first(attrs, "voice"),
        "name": _first(attrs, "voice-name"),
        "languages": _first(attrs, "voice-languages"),
        "gender": _first(attrs, "gender"),
        "age": _integer(attrs, "age"),
        "variant": _integer(attrs, "variant"),
    }
    return VoiceDirective(**values) if any(value is not None for value in values.values()) else None


def _pronunciation(attrs: Mapping[str, Any]) -> PronunciationDirective | None:
    phonemes = _first(attrs, "ph")
    alphabet = _first(attrs, "alphabet")
    if phonemes is None:
        phonemes = _first(attrs, "ipa", "sampa")
        if phonemes is not None and alphabet is None:
            alphabet = "ipa" if "ipa" in attrs else "sampa"
    if phonemes is None:
        return None
    return PronunciationDirective(phonemes, alphabet or "ipa")


def _prosody_fields(attrs: Mapping[str, Any], tag: str) -> dict[str, str]:
    if tag not in {"prosody", "voice", "directive"}:
        return {}
    return {
        key: value
        for key in ("volume", "rate", "pitch")
        if (value := _first(attrs, key)) is not None
    }


def _audio(attrs: Mapping[str, Any]) -> AudioDirective | None:
    src = _first(attrs, "src")
    if src is None:
        return None
    clip = _first(attrs, "clip")
    clip_begin, clip_end = _clip_bounds(clip)
    repeat = _first(attrs, "repeat")
    repeat_duration = _first(attrs, "repeatdur", "repeatDur")
    return AudioDirective(
        src=src,
        description=_first(attrs, "desc"),
        clip_begin=clip_begin,
        clip_end=clip_end,
        speed=_first(attrs, "speed"),
        repeat_duration=repeat_duration,
        repeat_count=float(repeat) if repeat is not None else None,
        sound_level=_first(attrs, "level"),
    )


def _clip_bounds(clip: str | None) -> tuple[str | None, str | None]:
    if clip is None:
        return None, None
    if "-" not in clip:
        return clip, None
    return tuple(clip.split("-", 1))  # type: ignore[return-value]


def _extension(attrs: Mapping[str, Any]) -> ExtensionDirective | None:
    name = _first(attrs, "ext")
    if name is None:
        return None
    params = {str(key): str(value) for key, value in attrs.items() if key not in {"ext", "tag"}}
    return ExtensionDirective(name, params)


def _first(attrs: Mapping[str, Any], *names: str) -> str | None:
    for name in names:
        value = attrs.get(name)
        if value is not None:
            return str(value)
    return None


def _integer(attrs: Mapping[str, Any], name: str) -> int | None:
    value = _first(attrs, name)
    return int(value) if value is not None else None
