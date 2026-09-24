from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Literal

from .exceptions import ConfigurationError

_DURATION_RE = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(ms|s)?\s*$", re.I)
_PAUSE_KEYS = frozenset(
    {"weak", "clause", "sentence", "paragraph", "parenthetical", "voice_change"}
)


def parse_duration(value: object, *, field_name: str = "duration") -> float:
    """Parse a portable duration and return finite, non-negative seconds.

    Numbers and unitless strings are seconds. Strings with ``ms`` or ``s`` are
    normalized to seconds so equivalent spellings have identical semantics.
    """
    if isinstance(value, bool):
        raise ConfigurationError(f"{field_name} must be a duration, not a boolean")
    if isinstance(value, (int, float)):
        seconds = float(value)
    elif isinstance(value, str):
        match = _DURATION_RE.fullmatch(value)
        if match is None:
            raise ConfigurationError(
                f"{field_name} must be a finite non-negative number of seconds or use ms/s syntax"
            )
        seconds = float(match.group(1))
        if match.group(2) and match.group(2).lower() == "ms":
            seconds /= 1000.0
    else:
        raise ConfigurationError(f"{field_name} must be a number or duration string")
    if not math.isfinite(seconds) or seconds < 0:
        raise ConfigurationError(f"{field_name} must be finite and non-negative")
    return seconds


def _validate_bool(value: object, field_name: str) -> None:
    if not isinstance(value, bool):
        raise ConfigurationError(f"{field_name} must be a boolean")


@dataclass(frozen=True, slots=True)
class PauseConfig:
    mode: Literal["tts", "manual", "auto"] = "tts"
    weak: float = 0.15
    clause: float = 0.30
    sentence: float = 0.60
    paragraph: float = 1.00
    parenthetical: float = 0.15
    voice_change: float = 0.15
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.mode not in {"tts", "manual", "auto"}:
            raise ConfigurationError("pauses.mode must be one of 'tts', 'manual', or 'auto'")
        _validate_bool(self.enabled, "pauses.enabled")
        for name in ("weak", "clause", "sentence", "paragraph", "parenthetical", "voice_change"):
            value = parse_duration(getattr(self, name), field_name=f"pauses.{name}")
            object.__setattr__(self, name, value)


@dataclass(frozen=True, slots=True)
class LinguisticsConfig:
    use_spacy: bool | None = None
    spacy_model: str | None = None
    spacy_model_size: Literal["sm", "md", "lg", "trf"] | None = None
    require_spacy: bool = False

    def __post_init__(self) -> None:
        for name in ("use_spacy", "require_spacy"):
            value = getattr(self, name)
            if value is not None:
                _validate_bool(value, f"linguistics.{name}")
        if self.spacy_model_size is not None and self.spacy_model_size not in {
            "sm",
            "md",
            "lg",
            "trf",
        }:
            raise ConfigurationError("linguistics.spacy_model_size is unsupported")


@dataclass(frozen=True, slots=True)
class SSMDConfig:
    parse_yaml_header: bool = True
    pause_overrides: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        _validate_bool(self.parse_yaml_header, "ssmd.parse_yaml_header")
        if self.pause_overrides is not None:
            if not isinstance(self.pause_overrides, Mapping):
                raise ConfigurationError("ssmd.pause_overrides must be a mapping")
            for key, value in self.pause_overrides.items():
                if key == "enabled":
                    _validate_bool(value, "ssmd.pause_overrides.enabled")
                elif key in _PAUSE_KEYS:
                    parse_duration(value, field_name=f"ssmd.pause_overrides.{key}")
                else:
                    raise ConfigurationError(f"ssmd.pause_overrides.{key} is unsupported")


@dataclass(frozen=True, slots=True)
class PlannerConfig:
    language: str
    document_format: Literal["plain", "ssmd"] = "plain"
    text_preparation: Literal["spokenform", "identity"] = "spokenform"
    unit: Literal["paragraph", "sentence"] = "paragraph"
    pauses: PauseConfig = field(default_factory=PauseConfig)
    linguistics: LinguisticsConfig = field(default_factory=LinguisticsConfig)
    ssmd: SSMDConfig = field(default_factory=SSMDConfig)
    overlap_mode: Literal["snap", "strict"] = "snap"
    language_aliases: Mapping[str, str] = field(default_factory=dict)
    diagnostics: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.language, str) or not self.language.strip():
            raise ConfigurationError("language must be a non-empty string")
        if self.document_format not in {"plain", "ssmd"}:
            raise ConfigurationError("document_format must be 'plain' or 'ssmd'")
        if self.text_preparation not in {"spokenform", "identity"}:
            raise ConfigurationError("text_preparation must be 'spokenform' or 'identity'")
        if self.unit not in {"paragraph", "sentence"}:
            raise ConfigurationError("unit must be 'paragraph' or 'sentence'")
        if self.overlap_mode not in {"snap", "strict"}:
            raise ConfigurationError("overlap_mode must be 'snap' or 'strict'")
        if not isinstance(self.language_aliases, Mapping):
            raise ConfigurationError("language_aliases must be a string-to-string mapping")
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.language_aliases.items()
        ):
            raise ConfigurationError("language_aliases must contain only string keys and values")
        _validate_bool(self.diagnostics, "diagnostics")


def semantic_config(config: PlannerConfig | Mapping[str, object]) -> dict[str, object]:
    """Return only configuration fields that can change the planning result."""
    value = asdict(config) if isinstance(config, PlannerConfig) else dict(config)
    value.pop("diagnostics", None)
    return value


__all__ = [
    "LinguisticsConfig",
    "PauseConfig",
    "PlannerConfig",
    "SSMDConfig",
    "parse_duration",
    "semantic_config",
]
