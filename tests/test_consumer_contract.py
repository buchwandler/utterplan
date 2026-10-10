from __future__ import annotations

from pathlib import Path

from utterplan import (
    FlowPlan,
    PauseConfig,
    PauseIntent,
    PlannerConfig,
    UtterancePlanner,
    compile_document,
)


def _fake_renderer(plan: FlowPlan) -> list[tuple[str, str, tuple[str, ...], PauseIntent | None]]:
    """Consume only local v5 flow, without compiler lookup tables or joins."""
    rendered = []
    for unit in plan.flow:
        for segment in unit.segments:
            rendered.append(
                (
                    segment.text,
                    segment.language,
                    tuple(token.surface(segment.text) for token in segment.tokens),
                    segment.pause_after,
                )
            )
    return rendered


def assert_public_consumer_contract(plan: FlowPlan) -> None:
    serialized = plan.to_dict()
    assert serialized["schema_version"] == 5
    assert "flow" in serialized
    assert not {
        "source",
        "texts",
        "tokens",
        "segments",
        "units",
        "annotations",
        "boundaries",
        "semantic_boundaries",
        "document_metadata",
        "diagnostics",
    }.intersection(serialized)

    for unit in plan.flow:
        for segment in unit.segments:
            assert segment.language
            previous_end = 0
            for token in segment.tokens:
                assert token.start >= previous_end
                assert token.end <= len(segment.text)
                assert segment.text[token.start : token.end] == token.surface(segment.text)
                previous_end = token.end
            assert segment.pause_before is None or isinstance(segment.pause_before, PauseIntent)
            assert segment.pause_after is None or isinstance(segment.pause_after, PauseIntent)

    restored = FlowPlan.from_toml(plan.to_toml())
    assert restored == plan
    assert restored.plan_id == plan.plan_id


def test_flow_plan_is_sufficient_for_a_fake_renderer() -> None:
    text = """---
ssmd_version: "0.9"
voice_bindings:
  narrator: voice-a
---
One. @mark [Two]{voice="narrator"}."""
    plan = UtterancePlanner(
        PlannerConfig(language="en-us", document_format="ssmd", text_preparation="identity")
    ).plan(text)

    rendered = _fake_renderer(plan)

    assert rendered
    assert rendered[0][1] == "en-us"
    assert any("Two" in surface for item in rendered for surface in item[2])
    assert plan.document.semantics["voice_bindings"] == {"narrator": "voice-a"}
    segment = next(
        segment for unit in plan.flow for segment in unit.segments if segment.directives.voice
    )
    assert segment.directives.voice is not None
    assert segment.directives.voice.reference == "narrator"
    assert any("mark" in segment.markers for unit in plan.flow for segment in unit.segments)
    assert_public_consumer_contract(plan)


def test_explicit_and_parenthetical_pauses_are_semantic_intents() -> None:
    explicit = UtterancePlanner(
        PlannerConfig(language="en-us", document_format="ssmd", text_preparation="identity")
    ).plan("Hello ...c world")
    parenthetical = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            text_preparation="identity",
            pauses=PauseConfig(mode="auto"),
        )
    ).plan("The backup battery (still warm) sat beside the console.")

    assert any(
        pause is not None
        for unit in explicit.flow
        for segment in unit.segments
        for pause in (segment.pause_before, segment.pause_after)
    )
    assert any(
        pause == PauseIntent("parenthetical")
        for unit in parenthetical.flow
        for segment in unit.segments
        for pause in (segment.pause_before, segment.pause_after)
    )
    assert_public_consumer_contract(explicit)
    assert_public_consumer_contract(parenthetical)


def test_multilingual_and_sentence_units_remain_in_render_order() -> None:
    plan = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
            unit="sentence",
            text_preparation="identity",
        )
    ).plan('One. [Bonjour.]{lang="fr"}')

    rendered = _fake_renderer(plan)
    assert [item[1] for item in rendered] == ["en-us", "fr"]
    assert len(plan.flow) == 2
    assert [[segment.text for segment in unit.segments] for unit in plan.flow] == [
        ["One."],
        ["Bonjour."],
    ]
    assert_public_consumer_contract(plan)


def test_zero_width_media_is_available_from_the_owning_segment() -> None:
    uri = "sfx:impact.knock?seed=42"
    plan = UtterancePlanner(
        PlannerConfig(language="en-us", document_format="ssmd", text_preparation="identity")
    ).plan(f'Before. []{{src="{uri}"}} After.')

    rendered = []
    for unit in plan.flow:
        for segment in unit.segments:
            audio = segment.directives.audio
            rendered.append(
                ("audio", audio.src, segment.text) if audio else ("speech", None, segment.text)
            )

    assert [item[0] for item in rendered] == ["speech", "audio", "speech"]
    assert rendered[1] == ("audio", uri, "")
    assert_public_consumer_contract(plan)


def test_shared_fixture_has_one_canonical_v5_interpretation() -> None:
    fixtures = Path(__file__).parent / "fixtures"
    source = (fixtures / "canonical_consumer_contract.ssmd").read_text(encoding="utf-8")
    expected = FlowPlan.load(fixtures / "canonical_consumer_contract.expected.toml")
    result = compile_document(
        source,
        input_format="ssmd",
        config=PlannerConfig(language="fr-FR", document_format="ssmd", text_preparation="identity"),
    )

    assert result.plan.plan_id == expected.plan_id
    assert result.plan.flow == expected.flow
    assert result.plan.document == expected.document
    assert result.plan.linguistics == expected.linguistics
    assert result.plan.flow[0].segments[0].directives.voice is not None
    assert result.plan.flow[0].segments[0].pause_after == PauseIntent("sentence")
    assert_public_consumer_contract(result.plan)


def test_trace_does_not_change_public_consumer_plan() -> None:
    config = PlannerConfig(language="en-us", document_format="plain")
    plain = compile_document("Dr. has 5 kg.", input_format="plain", config=config)
    traced = compile_document("Dr. has 5 kg.", input_format="plain", config=config, trace=True)

    assert traced.trace is not None
    assert traced.plan.to_toml() == plain.plan.to_toml()
    assert traced.plan.plan_id == plain.plan.plan_id
    assert_public_consumer_contract(traced.plan)
