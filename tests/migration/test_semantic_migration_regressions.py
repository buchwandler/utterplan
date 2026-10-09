from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.compiler_helpers import CompilerTestPlanner as UtterancePlanner
from utterplan import FlowPlan

from .cases import CASES

ROOT = Path(__file__).parent
GOLDENS = ROOT / "goldens"


def _semantic_projection(plan: Any) -> dict[str, Any]:
    data = plan.to_dict()
    return {
        "texts": data["texts"],
        "preparation": {
            "backend": data["preparation"]["backend"],
            "languages": data["preparation"]["languages"],
            "replacements": data["preparation"]["replacements"],
        },
        "languages": data["languages"],
        "annotations": data["annotations"],
        "boundaries": [
            {
                **{
                    key: boundary[key]
                    for key in ("position", "kind", "origin", "strength")
                    if key in boundary
                },
                "attrs": {
                    key: value
                    for key, value in boundary.get("attrs", {}).items()
                    if key != "pause_origin"
                },
            }
            for boundary in data["boundaries"]
        ],
        "segments": [
            {
                key: segment[key]
                for key in (
                    "text",
                    "spoken_start",
                    "spoken_end",
                    "language",
                    "paragraph",
                    "sentence",
                    "clause",
                    "directives",
                    "token_indices",
                    "annotation_ids",
                )
            }
            for segment in data["segments"]
        ],
        "units": [
            {
                key: unit[key]
                for key in ("kind", "spoken_start", "spoken_end", "segment_ids", "marker_ids")
            }
            for unit in data["units"]
        ],
        "markers": [
            {key: marker[key] for key in ("name", "spoken_position", "attrs")}
            for marker in data["markers"]
        ],
        "document_metadata": data["document_metadata"],
        "language_detection": data["document_metadata"].get("language_detection"),
    }


def test_migration_corpus_covers_required_case_groups() -> None:
    names = {case.name for case in CASES}
    assert {"plain_single", "plain_empty", "plain_unicode_punctuation"} <= names
    assert {"spokenform_numbers", "spokenform_date_time", "multilingual_preparation"} <= names
    assert {"clausal_comma", "parenthetical", "ssmd_break", "ssmd_pause_defaults"} <= names
    assert {
        "ssmd_language",
        "ssmd_pronunciation",
        "ssmd_voice",
        "ssmd_header_voice",
        "ssmd_prosody",
        "ssmd_emphasis",
        "ssmd_audio",
        "ssmd_marker",
        "ssmd_language_detection",
    } <= names


def test_migration_cases_roundtrip_without_renderer_state() -> None:
    forbidden = {
        "model_token_ids",
        "onnx_model",
        "session",
        "audio_samples",
    }
    for case in CASES:
        plan = UtterancePlanner(case.config).compile(case.text).plan
        restored = FlowPlan.from_toml(plan.to_toml())
        assert restored == plan
        serialized = json.dumps(plan.to_dict(), ensure_ascii=False)
        assert not any(f'"{field}"' in serialized for field in forbidden)


def test_migration_goldens_match_semantic_plan_output() -> None:
    by_name = {case.name: case for case in CASES}
    for path in sorted(GOLDENS.glob("*.json")):
        case = by_name[path.stem]
        expected = json.loads(path.read_text(encoding="utf-8"))
        actual = _semantic_projection(UtterancePlanner(case.config).plan(case.text))
        for key, expected_value in expected.items():
            if key == "segments":
                expected_value = [
                    {
                        name: value
                        for name, value in segment.items()
                        if name not in {"pause_before", "pause_after"}
                    }
                    for segment in expected_value
                ]
            if key == "boundaries":
                expected_value = [
                    {
                        **{name: value for name, value in boundary.items() if name != "seconds"},
                        "attrs": {
                            name: value
                            for name, value in boundary.get("attrs", {}).items()
                            if name != "pause_origin"
                        },
                    }
                    for boundary in expected_value
                ]
            assert actual[key] == expected_value
