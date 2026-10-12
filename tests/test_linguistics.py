import re
import sys
from types import SimpleNamespace

import pytest

from tests.compiler_helpers import CompilerTestPlanner as UtterancePlanner
from utterplan import (
    FlowPlan,
    LinguisticsConfig,
    PlannerConfig,
    UtterancePlan,
)
from utterplan.language import LanguageRun
from utterplan.linguistics import LinguisticResourcePool, analyze_run_analyses


class FakeProviderDoc(list):
    def __init__(self, text: str, tokens: list[SimpleNamespace]) -> None:
        super().__init__(tokens)
        self.text = text
        self.sents = ()


def test_run_analysis_is_lightweight_and_request_local():
    pool = LinguisticResourcePool()

    class Pipeline:
        def __call__(self, text):
            return [SimpleNamespace(idx=0, text=text, pos_="NOUN", tag_="NN", lemma_=text)]

    pool.pipeline = lambda model, require=False: Pipeline()
    analyses = analyze_run_analyses(
        "hello",
        (LanguageRun("lang-0", 0, 5, "en-us"),),
        PlannerConfig(language="en-us").linguistics.__class__(
            use_spacy=True, spacy_model="fake", require_spacy=True
        ),
        pool,
    )
    assert analyses[0].provider_doc is not None
    assert analyses[0].tokens[0].lemma == "hello"


def test_provider_documents_are_not_serialized():
    plan = UtterancePlanner(PlannerConfig(language="en-us")).plan("Hello world.")
    serialized = plan.to_toml()
    assert "provider_doc" not in serialized
    assert "spacy.tokens" not in serialized


def test_default_planner_falls_back_when_spacy_cannot_be_imported(monkeypatch):
    monkeypatch.setitem(sys.modules, "spacy", None)
    plan = UtterancePlanner(PlannerConfig(language="en-us")).plan("Hello world.")

    assert LinguisticsConfig().use_spacy is True
    assert plan.linguistic_runs[0].provider == "fallback"
    assert all(
        token.pos is None and token.tag is None and token.morph is None for token in plan.tokens
    )


def test_default_planner_falls_back_when_no_compatible_model_is_installed(monkeypatch):
    fake_spacy = SimpleNamespace(
        util=SimpleNamespace(get_installed_models=lambda: []),
        load=lambda model: pytest.fail(f"unexpected model load: {model}"),
    )
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)
    plan = UtterancePlanner(PlannerConfig(language="en-us")).plan("Hello world.")

    assert plan.linguistic_runs[0].provider == "fallback"


def test_default_planner_falls_back_when_auto_model_loading_fails(monkeypatch):
    def fail_load(model):
        raise OSError("model cannot load")

    fake_spacy = SimpleNamespace(
        util=SimpleNamespace(get_installed_models=lambda: ["en_core_web_sm"]),
        load=fail_load,
    )
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)
    plan = UtterancePlanner(PlannerConfig(language="en-us")).plan("Hello world.")

    assert plan.linguistic_runs[0].provider == "fallback"


def test_explicit_spacy_off_never_inspects_or_loads_spacy(monkeypatch):
    fake_spacy = SimpleNamespace(
        util=SimpleNamespace(
            get_installed_models=lambda: pytest.fail("spaCy must not be inspected")
        ),
        load=lambda model: pytest.fail(f"spaCy must not be loaded: {model}"),
    )
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)
    config = PlannerConfig(language="en-us", linguistics=LinguisticsConfig(use_spacy=False))
    plan = UtterancePlanner(config).plan("Hello world.")

    assert plan.linguistic_runs[0].provider == "fallback"
    assert plan.texts.spoken == "Hello world."
    assert all(token.pos is None and token.tag is None for token in plan.tokens)


def test_default_planner_uses_small_installed_spacy_model_and_reuses_it(monkeypatch):
    loaded_models = []
    model_names = ["en_core_web_lg", "en_core_web_trf", "en_core_web_sm"]

    class Pipeline:
        meta = {"version": "1.0"}

        def __call__(self, text):
            tags = {
                "I": ("PRON", "PRP", "I", "Case=Nom"),
                "live": ("VERB", "VBP", "live", "Tense=Pres|VerbForm=Fin"),
                "here.": ("ADV", "RB", "here", ""),
            }
            return FakeProviderDoc(
                text,
                [
                    SimpleNamespace(
                        idx=match.start(),
                        text=match.group(0),
                        pos_=tags.get(match.group(0), ("X", "", "", ""))[0],
                        tag_=tags.get(match.group(0), ("X", "", "", ""))[1],
                        lemma_=tags.get(match.group(0), ("X", "", "", ""))[2],
                        morph=tags.get(match.group(0), ("X", "", "", ""))[3],
                    )
                    for match in re.finditer(r"\S+", text)
                ],
            )

    pipeline = Pipeline()
    fake_spacy = SimpleNamespace(
        __version__="3.7.0",
        util=SimpleNamespace(get_installed_models=lambda: model_names),
        load=lambda model: loaded_models.append(model) or pipeline,
    )
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)
    planner = UtterancePlanner(PlannerConfig(language="en-us", text_preparation="identity"))

    first = planner.plan("I live here.")
    second = planner.plan("I live here.")
    live = next(token for token in first.tokens if token.text == "live")

    assert LinguisticsConfig().use_spacy is True
    assert loaded_models == ["en_core_web_sm"]
    assert first.linguistic_runs[0].provider == "spacy"
    assert first.linguistic_runs[0].model == "en_core_web_sm"
    assert second.linguistic_runs[0].provider == "spacy"
    assert (live.pos, live.tag, live.lemma, live.morph) == (
        "VERB",
        "VBP",
        "live",
        "Tense=Pres|VerbForm=Fin",
    )


def test_spacy_enrichment_does_not_collapse_sentence_topology(monkeypatch):
    class Pipeline:
        def __call__(self, text):
            return FakeProviderDoc(
                text,
                [
                    SimpleNamespace(
                        idx=match.start(),
                        text=match.group(0),
                        pos_="NOUN",
                        tag_="NN",
                        lemma_=match.group(0).lower(),
                        morph="",
                    )
                    for match in re.finditer(r"\S+", text)
                ],
            )

    monkeypatch.setitem(sys.modules, "spacy", SimpleNamespace(__version__="3.7.0"))
    monkeypatch.setattr(
        LinguisticResourcePool, "pipeline", lambda self, model, require=False: Pipeline()
    )
    config = PlannerConfig(
        language="en-us",
        document_format="plain",
        text_preparation="identity",
        linguistics=LinguisticsConfig(use_spacy=True, spacy_model="fake_model", require_spacy=True),
    )

    plan = UtterancePlanner(config).plan("One sentence. Two sentences. Three sentences.")

    assert [segment.text for segment in plan.segments] == [
        "One sentence.",
        "Two sentences.",
        "Three sentences.",
    ]
    assert [(segment.paragraph, segment.sentence) for segment in plan.segments] == [
        (0, 0),
        (0, 1),
        (0, 2),
    ]
    assert len(plan.units) == 1
    assert [token.pos for token in plan.tokens] == ["NOUN"] * 6
    assert [(segment.spoken_start, segment.spoken_end) for segment in plan.segments] == [
        (0, 13),
        (14, 28),
        (29, 45),
    ]
    assert all(
        plan.texts.spoken[segment.spoken_start : segment.spoken_end] == segment.text
        for segment in plan.segments
    )


def test_clausal_boundaries_reuse_provider_document(monkeypatch):
    import phrasplit

    docs = []

    class Pipeline:
        def __call__(self, text):
            tokens = [
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
            doc = FakeProviderDoc(text, tokens)
            docs.append(doc)
            return doc

    pipeline = Pipeline()
    monkeypatch.setitem(sys.modules, "spacy", SimpleNamespace(__version__="3.7.0"))
    monkeypatch.setattr(
        LinguisticResourcePool,
        "pipeline",
        lambda self, model, require=False: pipeline,
    )
    source = "First sentence. I wanted to go, but it was raining."
    detected = []

    def detect_clause_boundaries(text, *, language, doc):
        detected.append((text, doc))
        return [
            SimpleNamespace(
                kind="clausal_comma",
                char_start=text.index(","),
            )
        ]

    monkeypatch.setattr(phrasplit, "detect_clause_boundaries", detect_clause_boundaries)
    config = PlannerConfig(
        language="en-us",
        document_format="plain",
        text_preparation="identity",
        linguistics=LinguisticsConfig(use_spacy=True, spacy_model="fake_model", require_spacy=True),
    )

    plan = UtterancePlanner(config).plan(source)

    assert len(docs) == 1
    assert detected == [(source, docs[-1])]
    boundary = next(item for item in plan.boundaries if item.kind == "clausal_comma")
    assert boundary.position == source.index(",") + 2
    semantic = next(item for item in plan.semantic_boundaries if item.kind == "clause")
    assert semantic.position == source.index(",") + 2
    assert semantic.attrs["detector_start"] == source.index(",")
    assert semantic.attrs["detector_end"] == source.index(",") + 1
    assert boundary.attrs["semantic_boundary_id"] == semantic.id
    assert semantic.id == "semantic-boundary-000001"
    assert any(item.kind == "sentence" for item in plan.semantic_boundaries)


def test_semantic_clause_is_a_boundary_opportunity_not_a_pause_intent(monkeypatch):
    import phrasplit

    class Pipeline:
        def __call__(self, text):
            tokens = [
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
            return FakeProviderDoc(text, tokens)

    monkeypatch.setitem(sys.modules, "spacy", SimpleNamespace(__version__="3.7.0"))
    monkeypatch.setattr(
        LinguisticResourcePool,
        "pipeline",
        lambda self, model, require=False: Pipeline(),
    )
    monkeypatch.setattr(
        phrasplit,
        "detect_clause_boundaries",
        lambda text, *, language, doc: [
            SimpleNamespace(kind="clausal_comma", char_start=text.index(","))
        ],
    )
    source = "I wanted to go, but it was raining."
    config = PlannerConfig(
        language="en-us",
        text_preparation="identity",
        linguistics=LinguisticsConfig(use_spacy=True, spacy_model="fake_model", require_spacy=True),
    )
    plan = UtterancePlanner(config).plan(source)

    clause = next(item for item in plan.semantic_boundaries if item.kind == "clause")
    assert (clause.position, clause.kind, clause.id) == (
        source.index(",") + 2,
        "clause",
        "semantic-boundary-000000",
    )
    assert len(plan.segments) == 2
    assert plan.segments[0].boundary_after == ("clause",)
    assert all(
        segment.pause_before is None and segment.pause_after is None for segment in plan.segments
    )


def test_fallback_does_not_attempt_clausal_boundary_detection(monkeypatch):
    import phrasplit

    def fail_if_called(*args, **kwargs):
        raise AssertionError("fallback analysis must not infer syntactic clauses")

    monkeypatch.setattr(phrasplit, "detect_clause_boundaries", fail_if_called)
    plan = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            text_preparation="identity",
            linguistics=LinguisticsConfig(use_spacy=False),
        )
    ).plan("I wanted to go, but it was raining.")

    assert not any(item.kind == "clausal_comma" for item in plan.boundaries)
    assert not any(item.kind == "clause" for item in plan.semantic_boundaries)


def _fake_spacy_plan(
    monkeypatch, *, tag: str = "VBP", morph: str = "Tense=Pres|VerbForm=Fin"
) -> UtterancePlan:
    class Pipeline:
        def __call__(self, text):
            values = (
                (0, "I", "PRON", "PRP", "I", "Case=Nom"),
                (2, "live", "VERB", tag, "live", morph),
                (7, "here", "ADV", "RB", "here", None),
                (11, ".", "PUNCT", ".", ".", None),
            )
            return FakeProviderDoc(
                text,
                [
                    SimpleNamespace(
                        idx=idx,
                        text=value,
                        pos_=pos,
                        tag_=token_tag,
                        lemma_=lemma,
                        morph=token_morph,
                    )
                    for idx, value, pos, token_tag, lemma, token_morph in values
                ],
            )

    monkeypatch.setitem(sys.modules, "spacy", SimpleNamespace(__version__="3.7.0"))
    monkeypatch.setattr(
        LinguisticResourcePool, "pipeline", lambda self, model, require=False: Pipeline()
    )
    config = PlannerConfig(
        language="en-us",
        text_preparation="identity",
        linguistics=LinguisticsConfig(use_spacy=True, spacy_model="fake_model", require_spacy=True),
    )
    return UtterancePlanner(config).plan("I live here.")


def test_fake_spacy_fields_and_provenance_survive_roundtrip(monkeypatch):
    plan = _fake_spacy_plan(monkeypatch)
    token = next(token for token in plan.tokens if token.text == "live")
    assert token.text == "live"
    assert token.pos == "VERB"
    assert token.tag == "VBP"
    assert token.lemma == "live"
    assert token.morph == "Tense=Pres|VerbForm=Fin"
    assert plan.linguistic_runs[0].provider == "spacy"
    assert plan.linguistic_runs[0].model == "fake_model"
    assert plan.linguistic_runs[0].provider_version == "3.7.0"
    serialized = plan.to_toml()
    assert "provider_doc" not in serialized
    assert "spacy.tokens" not in serialized
    restored = FlowPlan.from_toml(serialized)
    restored_pairs = [
        (segment, token)
        for unit in restored.flow
        for segment in unit.segments
        for token in segment.tokens
    ]
    _restored_segment, restored_token = next(
        (segment, token)
        for segment, token in restored_pairs
        if token.surface(segment.text) == "live"
    )
    assert restored_token.pos == "VERB"
    assert restored_token.tag == "VBP"
    assert restored_token.lemma == "live"
    assert restored_token.morph == "Tense=Pres|VerbForm=Fin"
    assert restored.linguistics[0].provider == "spacy"
    assert restored.linguistics[0].model == "fake_model"
    assert restored.linguistics[0].provider_version == "3.7.0"


def test_fallback_provenance_is_explicit():
    plan = UtterancePlanner(
        PlannerConfig(language="en-us", linguistics=LinguisticsConfig(use_spacy=False))
    ).plan("I live here.")
    assert plan.linguistic_runs[0].provider == "fallback"
    assert plan.linguistic_runs[0].model is None
    assert all(
        token.pos is None and token.tag is None and token.morph is None for token in plan.tokens
    )


def test_token_semantics_change_unit_hash_but_provenance_does_not(monkeypatch):
    left = _fake_spacy_plan(monkeypatch, tag="VBP")
    right = _fake_spacy_plan(monkeypatch, tag="VB")
    assert left.units[0].content_hash != right.units[0].content_hash
    changed_provenance = type(left.linguistic_runs[0])(
        language_run_id=left.linguistic_runs[0].language_run_id,
        provider="spacy",
        token_start=left.linguistic_runs[0].token_start,
        token_end=left.linguistic_runs[0].token_end,
        model="other_model",
        provider_version="other",
        model_version="other",
    )
    from dataclasses import replace

    metadata_only = replace(left, linguistic_runs=(changed_provenance,))
    assert metadata_only.units[0].content_hash == left.units[0].content_hash


def _count_analysis_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    original = LinguisticResourcePool.analyze

    def counted(self, text, run, config, *, phase="source_analysis", on_progress=None):
        calls.append(text)
        return original(self, text, run, config, phase=phase, on_progress=on_progress)

    monkeypatch.setattr(LinguisticResourcePool, "analyze", counted)
    return calls


def test_identity_preparation_analyzes_once_and_preserves_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _count_analysis_calls(monkeypatch)
    config = PlannerConfig(language="en-us", document_format="plain", text_preparation="identity")
    baseline = UtterancePlanner(config).plan("Hello world.")
    assert len(calls) == 1
    calls.clear()

    events = []
    observed = UtterancePlanner(config).plan("Hello world.", on_progress=events.append)

    assert len(calls) == 1
    assert observed.plan_id == baseline.plan_id
    assert observed.to_toml() == baseline.to_toml()
    assert observed.document_metadata["planning"]["linguistic_passes"] == 1
    skipped = next(
        event
        for event in events
        if event.kind == "phase.started" and event.phase == "source_analysis"
    )
    assert skipped.details["skipped"] is True
    assert [event.pass_index for event in events if event.kind == "run.started"] == [2]


def test_unchanged_spokenform_reuses_source_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _count_analysis_calls(monkeypatch)
    events = []
    plan = UtterancePlanner(
        PlannerConfig(language="en-us", document_format="plain", text_preparation="spokenform")
    ).plan("Hello world.", on_progress=events.append)

    assert plan.texts.spoken == "Hello world."
    assert calls == ["Hello world."]
    reused = [
        event
        for event in events
        if event.phase == "spoken_analysis" and event.details.get("reused") is True
    ]
    assert [event.kind for event in reused] == ["phase.started", "phase.completed"]
    assert not any(
        event.kind == "run.started" and event.phase == "spoken_analysis" for event in events
    )


def test_changed_spokenform_still_analyzes_prepared_text(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _count_analysis_calls(monkeypatch)
    source = "Dr. Smith lives here."
    plan = UtterancePlanner(
        PlannerConfig(language="en-us", document_format="plain", text_preparation="spokenform")
    ).plan(source)

    assert plan.texts.spoken == "Doctor Smith lives here."
    assert calls == [source, plan.texts.spoken]
