from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from .exceptions import LanguagePlanError


@dataclass(frozen=True, slots=True)
class LanguageRun:
    id: str
    spoken_start: int
    spoken_end: int
    language: str
    source: str = "document-default"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "spoken_start": self.spoken_start,
            "spoken_end": self.spoken_end,
            "language": self.language,
            "source": self.source,
        }


def preserve_language_tag(value: str) -> str:
    if not isinstance(value, str):
        raise LanguagePlanError("language must be a string")
    tag = value.strip()
    if not tag:
        raise LanguagePlanError("language must not be empty")
    return tag


def language_lookup_key(value: str) -> str:
    return preserve_language_tag(value).lower().replace("_", "-")


def normalize_language(language: str, aliases: dict[str, str] | None = None) -> str:
    value = language_lookup_key(language)
    alias_map = {
        language_lookup_key(key): language_lookup_key(alias)
        for key, alias in (aliases or {}).items()
    }
    return alias_map.get(value, value)


def build_language_runs(
    text: str,
    spans: Iterable[tuple[int, int, str, str]],
    default_language: str,
    aliases: dict[str, str] | None = None,
    *,
    preserve_tags: bool = False,
) -> tuple[LanguageRun, ...]:
    normalize = (
        preserve_language_tag if preserve_tags else lambda value: normalize_language(value, aliases)
    )
    default = normalize(default_language)
    explicit = [(start, end, normalize(lang), source) for start, end, lang, source in spans]
    for start, end, _lang, _source in explicit:
        if not (0 <= start < end <= len(text)):
            raise LanguagePlanError(f"language span {start}:{end} is outside spoken text")
    for index, left in enumerate(explicit):
        for right in explicit[index + 1 :]:
            if left[2] == right[2] or not (left[0] < right[1] and right[0] < left[1]):
                continue
            nested = (left[0] <= right[0] and right[1] <= left[1]) or (
                right[0] <= left[0] and left[1] <= right[1]
            )
            if not nested:
                raise LanguagePlanError(
                    f"Conflicting crossing language spans: {left[0]}:{left[1]} and {right[0]}:{right[1]}"
                )
    positions = sorted({0, len(text), *(point for span in explicit for point in span[:2])})
    runs: list[LanguageRun] = []
    for start, end in zip(positions, positions[1:], strict=False):
        if start == end:
            continue
        covering = [span for span in explicit if span[0] <= start and end <= span[1]]
        chosen = min(covering, key=lambda span: (span[1] - span[0], -span[0])) if covering else None
        language = chosen[2] if chosen else default
        source = chosen[3] if chosen else "document-default"
        if runs and runs[-1].language == language and runs[-1].spoken_end == start:
            runs[-1] = LanguageRun(runs[-1].id, runs[-1].spoken_start, end, language, source)
        else:
            runs.append(LanguageRun(f"lang-{len(runs)}", start, end, language, source))
    return tuple(runs)


def spans_from_annotations(annotations: Sequence[Any]) -> list[tuple[int, int, str, str]]:
    result: list[tuple[int, int, str, str]] = []
    for item in annotations:
        attrs = getattr(item, "attrs", {})
        language = attrs.get("lang") or attrs.get("language")
        if not language or str(attrs.get("scope", "")).lower() in {"pronunciation", "phoneme"}:
            continue
        start = getattr(item, "spoken_start", None)
        end = getattr(item, "spoken_end", None)
        if start is None or end is None:
            start = getattr(item, "structural_start", None)
            end = getattr(item, "structural_end", None)
        if start is not None and end is not None:
            result.append((int(start), int(end), str(language), "explicit-span"))
    return result
