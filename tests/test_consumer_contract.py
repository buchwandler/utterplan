from __future__ import annotations

from pathlib import Path

from utterplan import (
    FlowPlan,
    LinguisticsConfig,
    PauseIntent,
    PlannerConfig,
    UtterancePlanner,
    compile_document,
    preview_plan,
)
from utterplan.model import LegacyPauseKind


def _fake_renderer(
    plan: FlowPlan,
) -> list[tuple[str, str, tuple[str, ...], PauseIntent | LegacyPauseKind | None]]:
    """Consume only local v7 flow, without compiler lookup tables or joins."""
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


def _sentence_chunks(plan: FlowPlan) -> tuple[tuple[str, ...], ...]:
    chunks: list[tuple[str, ...]] = []
    pending: list[str] = []
    for unit in plan.flow:
        for segment in unit.segments:
            pending.append(segment.text)
            if {"sentence", "paragraph"}.intersection(segment.boundary_after):
                chunks.append(tuple(pending))
                pending = []
    if pending:
        chunks.append(tuple(pending))
    return tuple(chunks)


def _paragraph_chunks(plan: FlowPlan) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(segment.text for segment in unit.segments) for unit in plan.flow)


def _fake_token_budget_chunks(plan: FlowPlan, budget: int) -> tuple[tuple[str, ...], ...]:
    """Model a downstream counter; it deliberately does not use UtterPlan tokens."""
    chunks: list[tuple[str, ...]] = []
    pending: list[str] = []
    count = 0
    for unit in plan.flow:
        for segment in unit.segments:
            segment_count = len(segment.text.split())
            if pending and count + segment_count > budget:
                chunks.append(tuple(pending))
                pending = []
                count = 0
            pending.append(segment.text)
            count += segment_count
    if pending:
        chunks.append(tuple(pending))
    return tuple(chunks)


def _pause_strategy_view(plan: FlowPlan, strategy: str) -> tuple[object, ...]:
    segments = [segment for unit in plan.flow for segment in unit.segments]
    if strategy == "native":
        return tuple(segment.pause_before or segment.pause_after for segment in segments)
    if strategy == "automatic":
        return tuple((*segment.boundary_before, *segment.boundary_after) for segment in segments)
    if strategy == "manual":
        return tuple(
            (
                segment.pause_before,
                segment.pause_after,
                segment.boundary_before,
                segment.boundary_after,
            )
            for segment in segments
        )
    raise AssertionError(f"unknown fake renderer strategy: {strategy}")


def assert_public_consumer_contract(plan: FlowPlan) -> None:
    serialized = plan.to_dict()
    assert serialized["schema_version"] == 7
    assert "unit" not in serialized
    assert "flow" in serialized
    assert not {
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


def test_one_saved_plan_supports_downstream_chunk_and_pause_choices() -> None:
    source = "One two. ...500ms Three four five. Six seven.\n\nEight nine."
    plan = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
            text_preparation="identity",
        )
    ).plan(source)
    original_toml = plan.to_toml()
    original_id = plan.plan_id

    sentence_chunks = _sentence_chunks(plan)
    paragraph_chunks = _paragraph_chunks(plan)
    budget_chunks = _fake_token_budget_chunks(plan, budget=6)

    assert sentence_chunks == (
        ("One two.",),
        ("Three four five.",),
        ("Six seven.",),
        ("Eight nine.",),
    )
    assert paragraph_chunks == (("One two.", "Three four five.", "Six seven."), ("Eight nine.",))
    assert budget_chunks == (("One two.", "Three four five."), ("Six seven.", "Eight nine."))
    assert len({sentence_chunks, paragraph_chunks, budget_chunks}) == 3

    native = _pause_strategy_view(plan, "native")
    automatic = _pause_strategy_view(plan, "automatic")
    manual = _pause_strategy_view(plan, "manual")
    assert native[0] == PauseIntent("timed", "500ms")
    assert automatic[0] == ("sentence",)
    assert manual[0] == (None, PauseIntent("timed", "500ms"), (), ("sentence",))
    assert plan.plan_id == original_id
    assert plan.to_toml() == original_toml


def test_explicit_authored_pauses_and_parenthetical_boundaries_are_separate() -> None:
    explicit = UtterancePlanner(
        PlannerConfig(language="en-us", document_format="ssmd", text_preparation="identity")
    ).plan("Hello ...c world")
    parenthetical = UtterancePlanner(
        PlannerConfig(language="en-us", text_preparation="identity")
    ).plan("The backup battery (still warm) sat beside the console.")

    assert any(
        pause == PauseIntent("medium")
        for unit in explicit.flow
        for segment in unit.segments
        for pause in (segment.pause_before, segment.pause_after)
    )
    assert any(
        "parenthetical" in (*segment.boundary_before, *segment.boundary_after)
        for unit in parenthetical.flow
        for segment in unit.segments
    )
    assert all(
        pause is None
        or pause.type not in {"clause", "sentence", "paragraph", "parenthetical", "voice_change"}
        for unit in parenthetical.flow
        for segment in unit.segments
        for pause in (segment.pause_before, segment.pause_after)
    )
    assert_public_consumer_contract(explicit)
    assert_public_consumer_contract(parenthetical)


def test_multilingual_segments_remain_in_paragraph_local_render_order() -> None:
    plan = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
            text_preparation="identity",
        )
    ).plan('One. [Bonjour.]{lang="fr"}')

    rendered = _fake_renderer(plan)
    assert [item[1] for item in rendered] == ["en-us", "fr"]
    assert len(plan.flow) == 1
    assert [[segment.text for segment in unit.segments] for unit in plan.flow] == [
        [
            "One.",
            "Bonjour.",
        ]
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


def test_v5_fixture_boundary_semantics_are_projected_into_v7_opportunities() -> None:
    from utterplan.codecs.v5_toml import loads_v5_toml

    fixtures = Path(__file__).parent / "fixtures"
    source = (fixtures / "canonical_consumer_contract.ssmd").read_text(encoding="utf-8")
    expected = loads_v5_toml(
        (fixtures / "canonical_consumer_contract.expected.toml").read_text(encoding="utf-8")
    )
    result = compile_document(
        source,
        input_format="ssmd",
        config=PlannerConfig(
            language="fr-FR",
            document_format="ssmd",
            text_preparation="identity",
            linguistics=LinguisticsConfig(use_spacy=False),
        ),
    )

    current_segments = [segment for unit in result.plan.flow for segment in unit.segments]
    old_segments = [segment for unit in expected.flow for segment in unit.segments]
    assert result.plan.plan_id != expected.plan_id
    assert result.plan.source is not None and result.plan.source.text == source
    assert [segment.text for segment in current_segments] == [
        segment.text for segment in old_segments
    ]
    assert result.plan.document == expected.document
    assert result.plan.linguistics == expected.linguistics
    assert current_segments[0].directives.voice is not None
    assert current_segments[0].boundary_after == ("sentence", "voice_change")
    assert current_segments[0].pause_after is None
    assert old_segments[0].pause_after is not None
    assert old_segments[0].pause_after.to_dict() == "sentence"
    assert_public_consumer_contract(result.plan)


def test_trace_does_not_change_public_consumer_plan() -> None:
    config = PlannerConfig(language="en-us", document_format="plain")
    plain = compile_document("Dr. has 5 kg.", input_format="plain", config=config)
    traced = compile_document("Dr. has 5 kg.", input_format="plain", config=config, trace=True)

    assert traced.trace is not None
    assert traced.plan.to_toml() == plain.plan.to_toml()
    assert traced.plan.plan_id == plain.plan.plan_id
    assert_public_consumer_contract(traced.plan)


def test_exact_substitution_sentence_previews_three_comma_clauses() -> None:
    source = (
        'Three said, *Target [Null+1]{sub="Null plus one"} on approach*, '
        "and included the direction vectors."
    )
    result = compile_document(
        source,
        input_format="ssmd",
        config=PlannerConfig(
            language="en-us",
            document_format="ssmd",
            text_preparation="auto",
            linguistics=LinguisticsConfig(use_spacy=False),
        ),
    )
    plan = result.plan
    original_toml = plan.to_toml()
    original_id = plan.plan_id
    segments = [segment for unit in plan.flow for segment in unit.segments]

    assert "".join(segment.text for segment in segments) == (
        "Three said, Target Null plus one on approach, and included the direction vectors."
    )
    emphasis = next(segment for segment in segments if segment.directives.emphasis is not None)
    assert emphasis.text == "Target Null plus one on approach, "
    assert len(emphasis.replacements) == 1
    replacement = emphasis.replacements[0]
    assert emphasis.text[replacement.start : replacement.end] == "Null plus one"

    sentence = preview_plan(plan, chunk_by="sentence", pause_policy="automatic")
    clauses = preview_plan(plan, chunk_by="clause", pause_policy="automatic")
    assert len(sentence) == 1
    assert (
        sentence[0].text
        == "Three said, Target Null plus one on approach, and included the direction vectors."
    )
    assert [chunk.text for chunk in clauses] == [
        "Three said, ",
        "Target Null plus one on approach, ",
        "and included the direction vectors.",
    ]
    assert [chunk.automatic_pause for chunk in clauses] == ["clause", "clause", "sentence"]
    assert [chunk.boundary_after for chunk in clauses] == [("clause",), ("clause",), ()]

    assert plan.to_toml() == original_toml
    assert plan.plan_id == original_id
    assert_public_consumer_contract(plan)
