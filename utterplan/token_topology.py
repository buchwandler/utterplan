from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .exceptions import PlanValidationError


@dataclass(frozen=True, slots=True)
class TokenBoundaryConflict:
    token_index: int
    token_start: int
    token_end: int
    token_text: str
    provider: str | None
    position: int


def boundary_splits_lexical_content(
    position: int,
    *,
    token: Any,
    provider: str | None,
) -> bool:
    """Return whether a spoken-text boundary divides lexical content in a token.

    Fallback tokenization uses ``\\S+`` spans, so only an alphanumeric pair
    directly adjacent to the cut is protected. Lexical-provider tokens retain
    the projection rule: both sides of a partial token must contain a word
    character for the cut to be unsafe.
    """
    start = token.spoken_start
    end = token.spoken_end
    if not start < position < end:
        return False

    relative = position - start
    if provider == "fallback":
        return token.text[relative - 1].isalnum() and token.text[relative].isalnum()

    return _has_word_character(token.text[:relative]) and _has_word_character(token.text[relative:])


def find_boundary_conflict(
    position: int,
    *,
    tokens: Sequence[Any],
    token_providers: Sequence[str | None],
) -> TokenBoundaryConflict | None:
    """Find the token whose interior is split by a spoken-text position."""
    token_index = bisect_right(tokens, position, key=lambda item: item.spoken_start) - 1
    if token_index < 0:
        return None
    token = tokens[token_index]
    provider = token_providers[token_index] if token_index < len(token_providers) else None
    if not boundary_splits_lexical_content(position, token=token, provider=provider):
        return None
    return TokenBoundaryConflict(
        token_index=token_index,
        token_start=token.spoken_start,
        token_end=token.spoken_end,
        token_text=token.text,
        provider=provider,
        position=position,
    )


def validate_segment_token_edges(
    segments: Sequence[Any],
    tokens: Sequence[Any],
    token_providers: Sequence[str | None],
    *,
    conflict_code: str = "token.segment_split",
) -> None:
    """Raise an error for any unsafe segment edge."""
    for segment in segments:
        if segment.spoken_start == segment.spoken_end:
            continue
        for side, position in (
            ("start", segment.spoken_start),
            ("end", segment.spoken_end),
        ):
            conflict = find_boundary_conflict(
                position,
                tokens=tokens,
                token_providers=token_providers,
            )
            if conflict is None:
                continue
            raise PlanValidationError(
                f"compiler segment {segment.id} "
                f"[{segment.spoken_start}:{segment.spoken_end}] splits token "
                f"{conflict.token_index} "
                f"[{conflict.token_start}:{conflict.token_end}] at its {side}",
                code=conflict_code,
            )


def _has_word_character(value: str) -> bool:
    return any(character.isalnum() for character in value)
