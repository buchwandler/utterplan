from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

from .attempts import PlanningAttempt
from .config import PlannerConfig
from .exceptions import ConfigurationError
from .model import Diagnostic, FlowPlan
from .progress import ProgressCallback

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
    """Optional compiler provenance, separate from renderer input.

    ``structural_to_spoken`` and ``spoken_to_structural`` map Python-character
    boundaries between the SSMD-clean structural text and prepared speech.
    ``source_spans`` maps original-source character ranges to structural ranges.
    ``PreparationTraceUnit`` offsets use those same structural and spoken spaces.
    """

    document_language: str
    sequence_fallback_mode: Literal["spell", "preserve"]
    diagnostics: tuple[Diagnostic, ...] = ()
    units: tuple[PreparationTraceUnit, ...] = ()
    source_sha256: str = ""
    source_text: str = ""
    structural_text: str = ""
    spoken_text: str = ""
    config: Mapping[str, Any] = field(default_factory=dict)
    structural_to_spoken: tuple[int, ...] = ()
    spoken_to_structural: tuple[int, ...] = ()
    source_spans: tuple[Mapping[str, Any], ...] = ()
    compiler_plan: Mapping[str, Any] = field(default_factory=dict)
    renderability: Mapping[str, Any] = field(default_factory=dict)
    repairs: tuple[Mapping[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return the complete JSON-compatible trace payload."""
        return asdict(self)

    def to_toml(self) -> str:
        """Serialize this optional trace as a TOML sidecar."""
        from .trace_codec import dumps_trace

        return dumps_trace(self)

    @classmethod
    def from_toml(cls, value: object) -> PreparationTrace:
        """Load and validate an optional trace TOML sidecar."""
        from .trace_codec import loads_trace

        return loads_trace(value)


@dataclass(frozen=True, slots=True)
class CompileResult:
    """Canonical result of compiling one document into its semantic plan."""

    plan: FlowPlan
    diagnostics: tuple[Diagnostic, ...]
    trace: PreparationTrace | None = None


def compile_document(
    text: str,
    *,
    input_format: InputFormat = "ssmd",
    config: PlannerConfig,
    fallback_language: str | None = None,
    trace: bool = False,
    on_progress: ProgressCallback | None = None,
) -> CompileResult:
    """Compile one SSMD document or explicitly selected plain-text document.

    The document's declared SSMD language is authoritative. ``fallback_language``
    replaces the configured fallback for this request; it never forces a language
    over document semantics. ``PlannerConfig.language`` remains the compatibility
    fallback when ``fallback_language`` is omitted. The optional progress callback is synchronous and operational only; exceptions raised by it propagate to the caller.
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
        return planner.compile(text, config=effective_config, trace=trace, on_progress=on_progress)
    finally:
        planner.close()


def compile_attempt(
    text: str,
    *,
    input_format: InputFormat = "ssmd",
    config: PlannerConfig,
    fallback_language: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> PlanningAttempt:
    """Return a non-throwing renderability outcome for one input document."""
    if input_format not in {"ssmd", "plain"}:
        raise ConfigurationError("input_format must be 'ssmd' or 'plain'")
    if fallback_language is not None:
        if not isinstance(fallback_language, str) or not fallback_language.strip():
            raise ConfigurationError("fallback_language must be a non-empty string")
        config = replace(config, language=fallback_language)
    effective_config = replace(config, document_format=input_format)

    from .planner import UtterancePlanner

    planner = UtterancePlanner(effective_config)
    try:
        return planner.compile_attempt(
            text,
            config=effective_config,
            on_progress=on_progress,
        )
    finally:
        planner.close()


__all__ = [
    "CompileResult",
    "PreparationChange",
    "InputFormat",
    "PreparationTrace",
    "PreparationTraceUnit",
    "compile_document",
    "compile_attempt",
]
