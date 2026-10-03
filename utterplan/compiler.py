from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from .config import PlannerConfig
from .exceptions import ConfigurationError
from .model import Diagnostic, UtterancePlan

InputFormat = Literal["ssmd", "plain"]


@dataclass(frozen=True, slots=True)
class PreparationChange:
    """A spokenform change with structural-source and prepared-text offsets."""

    source_start: int | None
    source_end: int | None
    output_start: int | None
    output_end: int | None
    source: str | None = None
    replacement: str | None = None
    kind: str | None = None
    rule: str | None = None
    language: str | None = None


@dataclass(frozen=True, slots=True)
class PreparationTraceUnit:
    """Preparation explanation for a plan unit.

    Source offsets address parsed SSMD-clean structural text, while output offsets
    on transformations address prepared spoken text. Both use Python character
    indexes.
    """

    source_start: int | None
    source_end: int | None
    source_text: str
    prepared_text: str
    effective_language: str | None
    effective_languages: tuple[str, ...] = ()
    transformations: tuple[PreparationChange, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    split_reason: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PreparationTrace:
    """Optional diagnostic explanation of semantic preparation, not renderer input."""

    document_language: str
    sequence_fallback_mode: Literal["spell", "preserve"]
    diagnostics: tuple[Diagnostic, ...] = ()
    units: tuple[PreparationTraceUnit, ...] = ()


@dataclass(frozen=True, slots=True)
class CompileResult:
    """Canonical result of compiling one document into its semantic plan."""

    plan: UtterancePlan
    diagnostics: tuple[Diagnostic, ...]
    trace: PreparationTrace | None = None


def compile_document(
    text: str,
    *,
    input_format: InputFormat = "ssmd",
    config: PlannerConfig,
    fallback_language: str | None = None,
    trace: bool = False,
) -> CompileResult:
    """Compile one SSMD document or explicitly selected plain-text document.

    The document's declared SSMD language is authoritative. ``fallback_language``
    replaces the configured fallback for this request; it never forces a language
    over document semantics. ``PlannerConfig.language`` remains the compatibility
    fallback when ``fallback_language`` is omitted.
    """
    if input_format not in {"ssmd", "plain"}:
        raise ConfigurationError("input_format must be 'ssmd' or 'plain'")
    if not isinstance(trace, bool):
        raise TypeError("trace must be a boolean")
    if fallback_language is not None:
        if not isinstance(fallback_language, str) or not fallback_language.strip():
            raise ConfigurationError("fallback_language must be a non-empty string")
        config = replace(config, language=fallback_language)
    effective_config = replace(config, document_format=input_format)

    from .planner import UtterancePlanner

    planner = UtterancePlanner(effective_config)
    try:
        return planner.compile(text, config=effective_config, trace=trace)
    finally:
        planner.close()


__all__ = [
    "CompileResult",
    "PreparationChange",
    "InputFormat",
    "PreparationTrace",
    "PreparationTraceUnit",
    "compile_document",
]
