from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from dataclasses import fields
from types import SimpleNamespace

import pytest

from utterplan import (
    LinguisticsConfig,
    PlannerConfig,
    PlannerProgressEvent,
    ProgressCallback,
    UtterancePlanner,
    compile_document,
)

TEXT = "Hello world."


def _identity_config(**kwargs: object) -> PlannerConfig:
    return PlannerConfig(
        language="en-us",
        document_format="plain",
        text_preparation="identity",
        **kwargs,
    )


def test_public_progress_callback_reports_major_phases_and_runs() -> None:
    events: list[PlannerProgressEvent] = []
    planner = UtterancePlanner(_identity_config())

    plan = planner.plan(TEXT, on_progress=events.append)

    phases = [event.phase for event in events if event.kind == "phase.started"]
    assert phases == [
        "parse",
        "source_analysis",
        "preparation",
        "spoken_analysis",
        "segmentation",
        "finalization",
    ]
    for phase in phases:
        assert (
            sum(event.kind == "phase.completed" and event.phase == phase for event in events) == 1
        )

    run_events = [event for event in events if event.kind.startswith("run.")]
    assert [(event.kind, event.phase, event.completed, event.total) for event in run_events] == [
        ("run.started", "spoken_analysis", 0, 1),
        ("run.completed", "spoken_analysis", 1, 1),
    ]
    skipped_source = next(
        event
        for event in events
        if event.kind == "phase.started" and event.phase == "source_analysis"
    )
    assert skipped_source.details["skipped"] is True
    assert all(event.pass_total == 2 for event in run_events)
    assert all(event.language == "en-us" for event in run_events)
    assert all(event.char_count == len(TEXT) for event in run_events)
    assert all(event.provider == "fallback" and event.model is None for event in run_events)
    assert plan.texts.spoken == TEXT


def test_compile_document_forwards_progress_callback() -> None:
    events: list[PlannerProgressEvent] = []
    result = compile_document(
        TEXT,
        input_format="plain",
        config=_identity_config(),
        on_progress=events.append,
    )

    assert result.plan.texts.spoken == TEXT
    assert events
    assert events[0].kind == "phase.started"
    assert events[0].phase == "parse"


def test_planner_compile_forwards_progress_callback() -> None:
    events: list[PlannerProgressEvent] = []
    result = UtterancePlanner(_identity_config()).compile(TEXT, on_progress=events.append)

    assert result.plan.texts.spoken == TEXT
    assert any(event.phase == "finalization" for event in events)


def test_progress_callback_exceptions_propagate() -> None:
    class MarkerError(RuntimeError):
        pass

    def callback(_event: PlannerProgressEvent) -> None:
        raise MarkerError

    with pytest.raises(MarkerError):
        UtterancePlanner(_identity_config()).plan(TEXT, on_progress=callback)


def test_model_load_events_bracket_real_load_and_cached_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeline: list[str] = []

    class Pipeline:
        meta = {"version": "1.0"}

        def __call__(self, text: str) -> list[SimpleNamespace]:
            timeline.append("provider")
            return [
                SimpleNamespace(
                    idx=match.start(),
                    text=match.group(0),
                    pos_="NOUN",
                    tag_="NN",
                    lemma_=match.group(0).lower(),
                    morph="",
                )
                for match in re.finditer(r"\S+", text)
            ]

    pipeline = Pipeline()
    loaded: list[str] = []

    def load(model: str) -> Pipeline:
        timeline.append("load")
        loaded.append(model)
        return pipeline

    monkeypatch.setitem(
        sys.modules,
        "spacy",
        SimpleNamespace(__version__="3.7.0", load=load),
    )
    config = _identity_config(
        linguistics=LinguisticsConfig(use_spacy=True, spacy_model="fake_model", require_spacy=True)
    )
    events: list[PlannerProgressEvent] = []

    def report(event: PlannerProgressEvent) -> None:
        events.append(event)
        timeline.append(event.kind)

    planner = UtterancePlanner(config)
    planner.plan(TEXT, on_progress=report)
    planner.plan(TEXT, on_progress=report)

    assert loaded == ["fake_model"]
    assert [event.kind for event in events if event.kind.startswith("model.")] == [
        "model.started",
        "model.completed",
    ]
    model_events = [event for event in events if event.kind.startswith("model.")]
    assert all(event.phase == "spoken_analysis" for event in model_events)
    assert all(event.language == "en-us" for event in model_events)
    assert all(event.provider == "spacy" and event.model == "fake_model" for event in model_events)
    assert timeline.index("run.started") < timeline.index("model.started")
    assert (
        timeline.index("model.started") < timeline.index("load") < timeline.index("model.completed")
    )
    assert timeline.index("model.completed") < timeline.index("provider")
    assert timeline.index("provider") < timeline.index("run.completed")


def test_progress_callback_type_is_public() -> None:
    def callback(_event: PlannerProgressEvent) -> None:
        return None

    public_callback: ProgressCallback = callback
    assert callable(public_callback)


def test_callback_output_matches_baseline_and_events_are_public_primitives() -> None:
    source = "Dr. Smith lives here."
    config = PlannerConfig(language="en-us", document_format="plain", text_preparation="spokenform")
    baseline = UtterancePlanner(config).plan(source)
    events: list[PlannerProgressEvent] = []
    observed = UtterancePlanner(config).plan(source, on_progress=events.append)

    assert observed.plan_id == baseline.plan_id
    assert observed.to_json() == baseline.to_json()

    def is_public_value(value: object) -> bool:
        if value is None or isinstance(value, (str, int, float, bool)):
            return True
        if isinstance(value, Mapping):
            return all(
                isinstance(key, str) and is_public_value(item) for key, item in value.items()
            )
        if isinstance(value, (list, tuple)):
            return all(is_public_value(item) for item in value)
        return False

    assert events
    assert all(
        is_public_value(getattr(event, field.name)) for event in events for field in fields(event)
    )


def test_multilingual_run_progress_is_monotonic_and_matches_plan_runs() -> None:
    source = (
        '---\nssmd_version: "0.9"\nlanguage: en-us\n---\n'
        'Hello [bonjour]{lang="fr"} [hola.]{lang="es"}'
    )
    events: list[PlannerProgressEvent] = []
    plan = UtterancePlanner(
        PlannerConfig(language="en-us", document_format="ssmd", text_preparation="identity")
    ).plan(source, on_progress=events.append)

    started = [
        event
        for event in events
        if event.kind == "run.started" and event.phase == "spoken_analysis"
    ]
    completed = [
        event
        for event in events
        if event.kind == "run.completed" and event.phase == "spoken_analysis"
    ]
    expected_languages = [run.language for run in plan.languages]

    assert [event.language for event in started] == expected_languages
    assert [event.language for event in completed] == expected_languages
    assert [event.completed for event in started] == list(range(len(expected_languages)))
    assert [event.completed for event in completed] == list(range(1, len(expected_languages) + 1))
    assert all(event.total == len(expected_languages) for event in started + completed)
    assert all(event.pass_index == 2 and event.pass_total == 2 for event in started + completed)
