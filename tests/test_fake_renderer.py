from __future__ import annotations

import pytest

from utterplan import (
    AudioDirective,
    DocumentInfo,
    FlowPlan,
    FlowSegment,
    FlowUnit,
    LinguisticProvenance,
    PauseIntent,
    PlannerConfig,
    SegmentDirectives,
    TokenView,
    UtterancePlanner,
)


def render_flow(plan: FlowPlan) -> list[dict[str, object]]:
    """Consume executable flow in one pass, without external lookup tables."""
    rendered = []
    for unit in plan.flow:
        for segment in unit.segments:
            audio = segment.directives.audio
            rendered.append(
                {
                    "kind": "audio" if audio is not None else "speech",
                    "audio_src": audio.src if audio is not None else None,
                    "text": segment.text,
                    "language": segment.language,
                    "tokens": [token.surface(segment.text) for token in segment.tokens],
                    "pause_before": segment.pause_before,
                    "pause_after": segment.pause_after,
                    "markers": segment.markers,
                    "heading": segment.heading,
                }
            )
    return rendered


def test_v5_flow_model_is_sufficient_for_a_single_pass_renderer() -> None:
    first = FlowSegment(
        text="Hello, world.",
        language="en-US",
        pause_after=PauseIntent("medium"),
        tokens=(
            TokenView(0, 5, lemma="hello", pos="INTJ"),
            TokenView(5, 6, pos="PUNCT"),
            TokenView(7, 12, lemma="world", pos="NOUN"),
            TokenView(12, 13, pos="PUNCT"),
        ),
        markers=("scene-2",),
        heading=2,
    )
    second = FlowSegment(
        text="Wait.",
        language="en-US",
        pause_before=PauseIntent("timed", "500ms"),
        tokens=(TokenView(0, 4, pos="VERB"), TokenView(4, 5, pos="PUNCT")),
    )
    plan = FlowPlan(
        language="en-US",
        unit="sentence",
        flow=(FlowUnit((first, second)),),
        document=DocumentInfo(format="ssmd", ssmd_version="0.9", title="Example"),
        linguistics=(LinguisticProvenance("en-US", "fallback"),),
    )

    rendered = render_flow(plan)
    assert [item["text"] for item in rendered] == ["Hello, world.", "Wait."]
    assert rendered[0]["tokens"] == ["Hello", ",", "world", "."]
    assert rendered[0]["pause_after"] == PauseIntent("medium")
    assert rendered[1]["pause_before"] == PauseIntent("timed", "500ms")
    assert rendered[0]["markers"] == ("scene-2",) and rendered[0]["heading"] == 2
    assert not {"tokens", "boundaries", "annotations", "segments"}.intersection(plan.to_dict())
    assert FlowPlan.from_toml(plan.to_toml()) == plan


def test_v5_pause_and_local_token_invariants_are_checked() -> None:
    with pytest.raises(ValueError, match="requires time"):
        PauseIntent("timed")
    with pytest.raises(ValueError, match="only valid"):
        PauseIntent("sentence", "500ms")
    with pytest.raises(ValueError, match="ordered"):
        FlowSegment("abcdef", "en-US", tokens=(TokenView(2, 4), TokenView(1, 3)))


def test_compiled_flow_plan_is_sufficient_for_a_fake_renderer() -> None:
    text = """---
ssmd_version: "0.9"
voice_bindings:
  narrator: voice-a
---
[Hello]{voice="narrator"} @mark"""
    plan = UtterancePlanner(
        PlannerConfig(language="en-us", document_format="ssmd", text_preparation="identity")
    ).plan(text)

    rendered = render_flow(plan)
    assert rendered
    assert rendered[0]["text"] == "Hello"
    assert rendered[0]["language"] == "en-us"
    assert any("mark" in item["markers"] for item in rendered)
    assert plan.flow[0].segments[0].directives.voice is not None
    assert plan.document.semantics["voice_bindings"] == {"narrator": "voice-a"}
    assert FlowPlan.from_toml(plan.to_toml()) == plan


def test_fake_renderer_selects_media_from_owning_segment_directive() -> None:
    uri = "sfx:unknown.effect?x=y"
    plan = UtterancePlanner(
        PlannerConfig(language="en-us", document_format="ssmd", text_preparation="identity")
    ).plan(f'[]{{src="{uri}"}}')

    rendered = render_flow(plan)
    assert len(rendered) == 1
    assert rendered[0]["kind"] == "audio"
    assert rendered[0]["audio_src"] == uri
    assert rendered[0]["text"] == ""
    assert rendered[0]["tokens"] == []


def test_direct_audio_directive_round_trips_in_flow_model() -> None:
    segment = FlowSegment(
        text="",
        language="en-US",
        directives=SegmentDirectives(audio=AudioDirective(src="sfx:bell")),
    )
    plan = FlowPlan(language="en-US", unit="paragraph", flow=(FlowUnit((segment,)),))

    assert render_flow(plan)[0]["audio_src"] == "sfx:bell"
    assert FlowPlan.from_toml(plan.to_toml()) == plan
