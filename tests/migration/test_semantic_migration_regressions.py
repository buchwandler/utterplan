from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tests.compiler_helpers import CompilerTestPlanner as UtterancePlanner
from utterplan import FlowPlan

from .cases import CASES

ROOT = Path(__file__).parent
GOLDENS = ROOT / "goldens"


def _semantic_projection(plan: Any) -> dict[str, Any]:
    data = plan.to_dict()
    metadata = dict(data["document_metadata"])
    for key in ("text_preparation_mode", "text_preparation_requested"):
        metadata.pop(key, None)
    planning = metadata.get("planning")
    if isinstance(planning, dict):
        planning = dict(planning)
        for key in (
            "text_preparation_mode",
            "segmentation_repair_count",
            "degraded_linguistics",
            "linguistic_passes",
        ):
            planning.pop(key, None)
        metadata["planning"] = planning
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
                    and not (key == "strength" and boundary.get("origin") == "planner")
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
        "document_metadata": metadata,
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
            if key == "document_metadata":
                expected_value = dict(expected_value)
                for metadata_key in ("text_preparation_mode", "text_preparation_requested"):
                    expected_value.pop(metadata_key, None)
                expected_planning = expected_value.get("planning")
                if isinstance(expected_planning, dict):
                    expected_planning = dict(expected_planning)
                    for metadata_key in (
                        "text_preparation_mode",
                        "segmentation_repair_count",
                        "degraded_linguistics",
                        "linguistic_passes",
                    ):
                        expected_planning.pop(metadata_key, None)
                    expected_value["planning"] = expected_planning
            if key == "texts":
                # Frozen v7 fixtures use normalized horizontal spacing around structural controls.
                assert {
                    name: re.sub(r"[ \t]+", " ", value) for name, value in actual[key].items()
                } == {name: re.sub(r"[ \t]+", " ", value) for name, value in expected_value.items()}
                continue
            if key == "segments":
                spoken = actual["texts"]["spoken"]
                assert all(
                    spoken[segment["spoken_start"] : segment["spoken_end"]] == segment["text"]
                    for segment in actual[key]
                )
                actual_segments = [
                    {
                        name: value
                        for name, value in segment.items()
                        if name not in {"text", "spoken_start", "spoken_end"}
                    }
                    for segment in actual[key]
                ]
                expected_segments = [
                    {
                        name: value
                        for name, value in segment.items()
                        if name
                        not in {"text", "spoken_start", "spoken_end", "pause_before", "pause_after"}
                    }
                    for segment in expected_value
                ]
                assert actual_segments == expected_segments
                continue
            if key == "units":
                assert [
                    (item["kind"], item["segment_ids"], item["marker_ids"]) for item in actual[key]
                ] == [
                    (item["kind"], item["segment_ids"], item["marker_ids"])
                    for item in expected_value
                ]
                continue
            if key == "boundaries":
                expected_value = [
                    {
                        **{
                            name: value
                            for name, value in boundary.items()
                            if name != "seconds"
                            and not (name == "strength" and boundary.get("origin") == "planner")
                        },
                        "attrs": {
                            name: value
                            for name, value in boundary.get("attrs", {}).items()
                            if name != "pause_origin"
                        },
                    }
                    for boundary in expected_value
                ]
            if key == "annotations":
                # The leading separator is outside the language annotation after normalization is disabled.
                actual_annotations = [
                    {
                        name: value
                        for name, value in item.items()
                        if not (
                            item.get("kind") == "lang"
                            and name in {"structural_start", "spoken_start"}
                        )
                    }
                    for item in actual[key]
                ]
                expected_annotations = [
                    {
                        name: value
                        for name, value in item.items()
                        if not (
                            item.get("kind") == "lang"
                            and name in {"structural_start", "spoken_start"}
                        )
                    }
                    for item in expected_value
                ]
                assert actual_annotations == expected_annotations
                continue
            if key == "languages":
                # Historical v7 fixtures retain pre-change offsets; current separator ownership
                # is pinned directly in tests/test_preparation.py.
                assert [(item["id"], item["language"], item["source"]) for item in actual[key]] == [
                    (item["id"], item["language"], item["source"]) for item in expected_value
                ]
                continue
            assert actual[key] == expected_value
