from __future__ import annotations

import hashlib
import json
from typing import Any

UNIT_HASH_SCHEMA = "utterplan-unit-v2"

def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def semantic_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def unit_hash_payload(unit: Any) -> dict[str, Any]:
    marker_values: Any = getattr(unit, "marker_values", None)
    if marker_values is None:
        marker_values = getattr(unit, "marker_ids", ())
    markers = []
    for marker in marker_values:
        if hasattr(marker, "to_dict"):
            value = marker.to_dict()
            value.pop("id", None)
            markers.append(value)
        else:
            markers.append(marker)

    tokens = [
        {
            "text": token.text,
            "language": token.language,
            "lemma": token.lemma,
            "pos": token.pos,
            "tag": token.tag,
            "morph": token.morph,
        }
        for segment in unit.segments
        for token in (unit.tokens[index] for index in segment.token_indices)
    ]
    return {
        "hash_schema": UNIT_HASH_SCHEMA,
        "segments": [
            {
                "text": segment.text,
                "language": segment.language,
                "directives": segment.directives.to_dict(),
                "pause_before": segment.pause_before.to_dict(),
                "pause_after": segment.pause_after.to_dict(),
            }
            for segment in unit.segments
        ],
        "markers": markers,
        "tokens": tokens,
    }
