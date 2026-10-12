from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

BoundaryKind = Literal[
    "clause",
    "sentence",
    "paragraph",
    "parenthetical",
    "voice_change",
]

BOUNDARY_KIND_ORDER: dict[BoundaryKind, int] = {
    "clause": 10,
    "sentence": 20,
    "paragraph": 30,
    "parenthetical": 40,
    "voice_change": 50,
}


def canonicalize_boundary_kinds(values: Iterable[str]) -> tuple[BoundaryKind, ...]:
    """Deduplicate and order boundary opportunities using the public canonical order."""
    if isinstance(values, str):
        raise ValueError("boundary kinds must be an iterable of kind names, not a string")
    unique: set[BoundaryKind] = set()
    for value in values:
        if not isinstance(value, str) or value not in BOUNDARY_KIND_ORDER:
            raise ValueError(f"unsupported boundary kind: {value!r}")
        unique.add(value)
    if "paragraph" in unique:
        unique.difference_update({"sentence", "clause"})
    elif "sentence" in unique:
        unique.discard("clause")
    return tuple(sorted(unique, key=BOUNDARY_KIND_ORDER.__getitem__))


def validate_canonical_boundary_kinds(values: Iterable[str]) -> tuple[BoundaryKind, ...]:
    """Validate a serialized boundary array without silently repairing its order or contents."""
    if isinstance(values, str):
        raise ValueError("boundary kinds must be an array of kind names")
    items = tuple(values)
    canonical = canonicalize_boundary_kinds(items)
    if len(items) != len(set(items)):
        raise ValueError("boundary kinds must not contain duplicates")
    if len(items) != len(canonical):
        raise ValueError("weaker structural boundary kinds must be omitted")
    if items != canonical:
        raise ValueError("boundary kinds must use canonical ordering")
    return canonical
