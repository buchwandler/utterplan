"""Deterministic context-aware timing for automatic RenderPlan pauses.

This module consumes only serializable FlowPlan facts and never loads NLP or
rendering/audio providers. Authored pause intent is resolved by the caller and
must not be sent through this automatic timing policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .model import TokenView

PauseTimingMode = Literal["fixed", "natural", "engaging"]
PAUSE_TIMING_ALGORITHM = "utterplan.pause-timing.v1"

_WORD_PATTERN = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)
_CLOSING_PUNCTUATION = "\"'”’»)]}〉》」』】〕〗〙〛"
_CONNECTIVES = frozenset(
    {
        "and",
        "but",
        "or",
        "so",
        "then",
        "yet",
        "because",
        "while",
        "when",
        "as",
        "which",
        "who",
        "that",
    }
)
_FUNCTION_POS = frozenset({"DET", "ADP", "AUX", "PART", "CCONJ", "SCONJ"})

_AMPLITUDE = {"natural": 700, "engaging": 1000}
_BOUNDARY_BIAS = {
    "natural": {"clause": 0, "sentence": 0, "paragraph": -30},
    "engaging": {"clause": -70, "sentence": -110, "paragraph": -100},
}
_FACTOR_LIMITS = {
    "natural": {
        "clause": (750, 1250),
        "sentence": (760, 1200),
        "paragraph": (820, 1180),
    },
    "engaging": {
        "clause": (600, 1150),
        "sentence": (600, 1150),
        "paragraph": (700, 1120),
    },
}


@dataclass(frozen=True, slots=True)
class PauseTimingConfig:
    """Select the automatic pause timing preset; fixed preserves old behavior."""

    mode: PauseTimingMode = "fixed"

    def __post_init__(self) -> None:
        if self.mode not in {"fixed", "natural", "engaging"}:
            raise ValueError(f"unsupported pause timing mode {self.mode!r}")


@dataclass(frozen=True, slots=True)
class PauseTimingContext:
    """Local facts around one already-materialized semantic boundary."""

    boundary: str
    language: str
    left_text: str
    right_text: str
    left_tokens: tuple[TokenView, ...] = ()
    right_tokens: tuple[TokenView, ...] = ()
    left_heading: int | None = None
    right_heading: int | None = None


@dataclass(frozen=True, slots=True)
class PauseTimingDecision:
    """Resolved milliseconds and an optional stable explanation for testing."""

    base_ms: int
    duration_ms: int
    factor_permille: int
    features: tuple[str, ...]


def resolve_automatic_pause_duration(
    base_ms: int,
    context: PauseTimingContext,
    config: PauseTimingConfig,
) -> PauseTimingDecision:
    """Scale an existing automatic pause using stable integer-only heuristics."""
    if type(base_ms) is not int:
        raise TypeError("base_ms must be an integer")
    if base_ms <= 0:
        return PauseTimingDecision(base_ms, 0, 1000, ("zero-base",))
    if config.mode == "fixed":
        return PauseTimingDecision(base_ms, base_ms, 1000, ("fixed",))
    if context.boundary == "voice_change":
        return PauseTimingDecision(base_ms, base_ms, 1000, ("fixed-boundary",))
    if context.boundary not in _BOUNDARY_BIAS[config.mode]:
        return PauseTimingDecision(base_ms, base_ms, 1000, ("unsupported-boundary",))

    raw = 0
    features: list[str] = []
    for adjustment, feature in (
        _length_adjustment(context.left_text, context.left_tokens),
        _punctuation_adjustment(context.left_text),
        _connective_adjustment(context),
        _pos_adjustment(context.left_tokens, context.right_tokens),
        _heading_adjustment(context),
    ):
        raw += adjustment
        if feature is not None:
            features.append(feature)

    amplitude = _AMPLITUDE[config.mode]
    bias = _BOUNDARY_BIAS[config.mode][context.boundary]
    scaled = bias + _integer_scale(raw, amplitude)
    low, high = _FACTOR_LIMITS[config.mode][context.boundary]
    factor = min(high, max(low, 1000 + scaled))
    duration = (base_ms * factor + 500) // 1000
    duration = ((duration + 5) // 10) * 10
    return PauseTimingDecision(base_ms, duration, factor, tuple(features))


def _integer_scale(value: int, amplitude: int) -> int:
    """Round a signed permille product to nearest integer, ties away from zero."""
    product = value * amplitude
    if product >= 0:
        return (product + 500) // 1000
    return -((-product + 500) // 1000)


def _length_adjustment(text: str, tokens: tuple[TokenView, ...]) -> tuple[int, str]:
    if tokens and any(token.pos is not None for token in tokens):
        count = sum(token.pos != "PUNCT" for token in tokens)
        source = "tokens"
    else:
        count = len(_WORD_PATTERN.findall(text))
        source = "text"
    if count <= 3:
        return -160, f"length:{source}:{count}"
    if count <= 7:
        return -100, f"length:{source}:{count}"
    if count <= 16:
        return 0, f"length:{source}:{count}"
    if count <= 25:
        return 60, f"length:{source}:{count}"
    return 100, f"length:{source}:{count}"


def _punctuation_adjustment(text: str) -> tuple[int, str | None]:
    ending = text.rstrip().rstrip(_CLOSING_PUNCTUATION)
    if ending.endswith(("...", "…")):
        return 160, "punctuation:ellipsis:+160"
    for punctuation, adjustment in (
        ("?", 60),
        ("!", 40),
        (":", 60),
        (";", 40),
        (",", -50),
        ("—", 20),
    ):
        if ending.endswith(punctuation):
            return adjustment, f"punctuation:{punctuation}:{adjustment:+d}"
    return 0, None


def _connective_adjustment(context: PauseTimingContext) -> tuple[int, str | None]:
    language = context.language.casefold().replace("_", "-").split("-", 1)[0]
    if language != "en":
        return 0, None
    word = _first_word(context.right_text, context.right_tokens)
    if word in _CONNECTIVES:
        return -90, f"connective:{word}:-90"
    return 0, None


def _first_word(text: str, tokens: tuple[TokenView, ...]) -> str:
    for token in tokens:
        if token.pos == "PUNCT":
            continue
        lemma = token.lemma.strip().casefold() if token.lemma else ""
        if lemma:
            return lemma
        surface = token.surface(text).strip().casefold()
        if surface:
            return surface
    match = _WORD_PATTERN.search(text)
    return match.group(0).casefold() if match else ""


def _pos_adjustment(
    left_tokens: tuple[TokenView, ...], right_tokens: tuple[TokenView, ...]
) -> tuple[int, str | None]:
    adjustment = 0
    features: list[str] = []
    next_pos = next((token.pos for token in right_tokens if token.pos != "PUNCT"), None)
    if next_pos in {"CCONJ", "SCONJ"}:
        adjustment -= 50
        features.append("pos:next-conjunction:-50")
    previous_pos = next(
        (token.pos for token in reversed(left_tokens) if token.pos != "PUNCT"), None
    )
    if previous_pos in _FUNCTION_POS:
        adjustment -= 80
        features.append("pos:final-function-word:-80")
    return adjustment, "+".join(features) if features else None


def _heading_adjustment(context: PauseTimingContext) -> tuple[int, str | None]:
    if context.right_heading is not None and context.right_heading != context.left_heading:
        return 120, "heading:transition:+120"
    return 0, None


__all__ = [
    "PAUSE_TIMING_ALGORITHM",
    "PauseTimingConfig",
    "PauseTimingContext",
    "PauseTimingDecision",
    "PauseTimingMode",
    "resolve_automatic_pause_duration",
]
