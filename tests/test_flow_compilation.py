from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from utterplan import (
    FlowPlan,
    LinguisticsConfig,
    PauseConfig,
    PlannerConfig,
    UtterancePlanner,
    compile_document,
)
from utterplan.exceptions import PlanValidationError
from utterplan.flow_projection import _token_providers, _tokens_for_segment
from utterplan.migrations.v4_to_v5 import migrate_v4_to_v5
from utterplan.model import LinguisticRun, TokenAnnotation


def _segments(plan: FlowPlan):
    return tuple(segment for unit in plan.flow for segment in unit.segments)


def test_fresh_compile_returns_current_v5_local_flow() -> None:
    text = 'Hello [world]{emphasis="strong"}.'
    config = PlannerConfig(language="en-us", document_format="ssmd", text_preparation="identity")
    result = compile_document(text, input_format="ssmd", config=config)
    planner = UtterancePlanner(config)
    try:
        planned = planner.plan(text)
    finally:
        planner.close()

    assert isinstance(result.plan, FlowPlan)
    assert result.plan.schema_version == 5
    assert planned == result.plan
    payload = result.plan.to_toml()
    assert payload == result.plan.to_toml()
    assert FlowPlan.from_toml(payload) == result.plan
    assert not hasattr(result.plan, "tokens")
    assert not hasattr(result.plan, "segments")
    assert any(segment.directives.emphasis is not None for segment in _segments(result.plan))
    for segment in _segments(result.plan):
        assert all(segment.text[token.start : token.end] for token in segment.tokens)


@pytest.mark.parametrize(
    "fixture_name",
    ("basic_en", "ssmd_breaks", "markers", "multilingual", "parenthetical", "spokenform_offsets"),
)
def test_fresh_compilation_converges_with_v4_migration_on_unambiguous_input(
    fixture_name: str,
) -> None:
    fixture = Path(__file__).parent / f"migration/fixtures/v4/{fixture_name}.utterplan.json"
    v4_plan = json.loads(fixture.read_text(encoding="utf-8"))
    old_config = v4_plan["config"]
    old_pauses = old_config.get("pauses", {})
    config = PlannerConfig(
        language=old_config["language"],
        document_format=old_config["document_format"],
        unit=old_config.get("unit", "paragraph"),
        text_preparation=old_config.get("text_preparation", "spokenform"),
        pauses=PauseConfig(
            mode=old_pauses.get("mode", "tts"),
            enabled=old_pauses.get("enabled", True),
        ),
    )
    fresh = compile_document(
        v4_plan["source"]["text"],
        input_format=old_config["document_format"],
        config=config,
    ).plan
    migrated = FlowPlan.from_dict(migrate_v4_to_v5(v4_plan))

    if fixture_name == "multilingual":
        # The compiler now preserves the inter-language whitespace on the right-hand
        # renderer segment instead of dropping it at the run boundary.
        assert fresh.flow != migrated.flow
        assert [[segment.text for segment in unit.segments] for unit in fresh.flow] == [
            ["Hello", " Bonjour."]
        ]
        assert fresh.document == migrated.document
        assert fresh.linguistics == migrated.linguistics
        assert fresh.language == migrated.language
        assert fresh.unit == migrated.unit
    else:
        assert fresh.plan_id == migrated.plan_id
        assert fresh.flow == migrated.flow
        assert fresh.document == migrated.document
        assert fresh.linguistics == migrated.linguistics
        assert fresh.language == migrated.language
        assert fresh.unit == migrated.unit


def test_fresh_compile_localizes_a_token_cut_by_ssmd_semantics() -> None:
    fixture = Path(__file__).parent / "migration/fixtures/v4/ssmd_09_comprehensive.utterplan.json"
    source = json.loads(fixture.read_text(encoding="utf-8"))["source"]["text"]
    result = compile_document(
        source,
        input_format="ssmd",
        config=PlannerConfig(
            language="sr-Latn",
            document_format="ssmd",
            text_preparation="identity",
        ),
    )

    segments = _segments(result.plan)
    water_segment = next(segment for segment in segments if segment.text == "H2O")
    assert any(segment.text == ", and" for segment in segments)
    assert any(
        token.start == 0 and token.end == 3 and water_segment.text[token.start : token.end] == "H2O"
        for token in water_segment.tokens
    )
    for segment in segments:
        for token in segment.tokens:
            assert segment.text[token.start : token.end]


def _project_partial_token(
    text: str,
    start: int,
    end: int,
    *,
    provider: str = "fallback",
    lemma: str | None = None,
):
    token = TokenAnnotation(0, len(text), text, lemma=lemma)
    plan = SimpleNamespace(
        texts=SimpleNamespace(spoken=text),
        tokens=(token,),
        linguistic_runs=(LinguisticRun("language-0001", provider, 0, 1),),
    )
    segment = SimpleNamespace(
        id="seg-000123",
        language="en-US",
        spoken_start=start,
        spoken_end=end,
        token_indices=(0,),
    )
    return _tokens_for_segment(
        plan,
        segment,
        _token_providers(plan),
        "$.flow[0].segments[0].tokens",
    )


@pytest.mark.parametrize(
    ("body", "expected_surface"),
    (
        ('[alpha]{emphasis="strong"}—beta', "alpha"),
        ('alpha—[beta]{emphasis="strong"}', "beta"),
    ),
)
def test_fresh_compile_localizes_fallback_tokens_at_internal_punctuation(
    body: str, expected_surface: str
) -> None:
    source = f'---\nssmd_version: "0.9"\nlanguage: en-US\n---\n{body}\n'
    result = compile_document(
        source,
        input_format="ssmd",
        config=PlannerConfig(
            language="en-US",
            document_format="ssmd",
            text_preparation="identity",
            linguistics=LinguisticsConfig(use_spacy=False),
        ),
    )

    assert result.plan.linguistics[0].provider == "fallback"
    segments = _segments(result.plan)
    assert any(
        segment.text[token.start : token.end] == expected_surface
        for segment in segments
        for token in segment.tokens
    )
    for segment in segments:
        assert all(segment.text[token.start : token.end] for token in segment.tokens)


@pytest.mark.parametrize(
    ("start", "end", "split_side"),
    ((0, 3, "end"), (2, 5, "start")),
)
def test_fallback_provider_rejects_true_alphanumeric_splits_with_coordinates(
    start: int, end: int, split_side: str
) -> None:
    with pytest.raises(PlanValidationError) as exc_info:
        _project_partial_token("hello", start, end, lemma="hello")

    error = exc_info.value
    assert error.code == "token.segment_split"
    assert error.path == "$.flow[0].segments[0].tokens"
    assert f"segment seg-000123 [{start}:{end}]" in str(error)
    assert f"token 0 [0:5] at its {split_side}" in str(error)


@pytest.mark.parametrize("provider", ("spacy", "unknown"))
def test_nonfallback_provider_keeps_punctuation_connected_partial_tokens_strict(
    provider: str,
) -> None:
    with pytest.raises(PlanValidationError) as exc_info:
        _project_partial_token("alpha—beta", 0, 5, provider=provider, lemma="alpha—beta")

    assert exc_info.value.code == "token.segment_split"


def test_fallback_partial_default_lemmas_are_casefolded_per_fragment() -> None:
    text = "Straße—Bahn"
    default_lemma = text.lower()

    left = _project_partial_token(text, 0, 6, lemma=default_lemma)
    right = _project_partial_token(text, 7, 11, lemma=default_lemma)

    assert [token.lemma for token in left] == ["strasse"]
    assert [token.lemma for token in right] == ["bahn"]
