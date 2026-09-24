from __future__ import annotations

from utterplan import PlannerConfig, UtterancePlanner


def render_semantic_plan(plan: object) -> list[dict[str, object]]:
    """Minimal engine-neutral consumer using only the public UtterancePlan shape."""
    segments = {segment.id: segment for segment in plan.segments}  # type: ignore[attr-defined]
    tokens = plan.tokens  # type: ignore[attr-defined]
    annotations = {annotation.id: annotation for annotation in plan.annotations}  # type: ignore[attr-defined]
    markers = {marker.id: marker for marker in plan.markers}  # type: ignore[attr-defined]
    rendered: list[dict[str, object]] = []
    for unit in plan.units:  # type: ignore[attr-defined]
        for segment_id in unit.segment_ids:
            segment = segments[segment_id]
            rendered.append(
                {
                    "unit": unit.id,
                    "text": segment.text,
                    "language": segment.language,
                    "tokens": [tokens[index].text for index in segment.token_indices],
                    "annotations": [
                        annotations[identifier].kind for identifier in segment.annotation_ids
                    ],
                    "pause_before": segment.pause_before.seconds,
                    "pause_after": segment.pause_after.seconds,
                    "directives": segment.directives.to_dict(),
                    "markers": [markers[identifier].name for identifier in unit.marker_ids],
                    "metadata": plan.document_metadata,
                }
            )
    return rendered


def test_public_utterplan_is_sufficient_for_a_fake_renderer() -> None:
    text = """---
ssmd_version: "0.9"
voice_bindings:
  narrator: voice-a
---
[Hello]{voice="narrator"} @mark"""
    plan = UtterancePlanner(PlannerConfig(language="en-us", text_preparation="identity")).plan(text)
    rendered = render_semantic_plan(plan)
    assert rendered
    assert rendered[0]["text"] == "Hello"
    assert rendered[0]["language"] == "en-us"
    assert rendered[0]["directives"]["voice"]["reference"] == "narrator"  # type: ignore[index]
    assert "voice_bindings" in rendered[0]["metadata"]  # type: ignore[operator]
    assert "mark" in {marker.name for marker in plan.markers}
