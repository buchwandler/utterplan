from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Literal

from .exceptions import ConfigurationError


def _validate_bool(value: object, field_name: str) -> None:
    if not isinstance(value, bool):
        raise ConfigurationError(f"{field_name} must be a boolean")


@dataclass(frozen=True, slots=True)
class PauseConfig:
    mode: Literal["tts", "manual", "auto"] = "tts"
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.mode not in {"tts", "manual", "auto"}:
            raise ConfigurationError("pauses.mode must be one of 'tts', 'manual', or 'auto'")
        _validate_bool(self.enabled, "pauses.enabled")


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

    def __post_init__(self) -> None:
        _validate_bool(self.parse_yaml_header, "ssmd.parse_yaml_header")


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
    renderability_mode: Literal["strict", "repair"] = "repair"
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
        if self.renderability_mode not in {"strict", "repair"}:
            raise ConfigurationError("renderability_mode must be 'strict' or 'repair'")
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
    "semantic_config",
]
