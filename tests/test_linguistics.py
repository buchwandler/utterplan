import sys
from types import SimpleNamespace

from utterplan import LinguisticsConfig, PlannerConfig, UtterancePlan, UtterancePlanner
from utterplan.language import LanguageRun
from utterplan.linguistics import LinguisticResourcePool, analyze_run_analyses


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
    serialized = plan.to_json()
    assert "provider_doc" not in serialized
    assert "spacy.tokens" not in serialized


def test_default_planner_does_not_load_spacy(monkeypatch):
    def fail_if_loaded(*args, **kwargs):
        raise AssertionError("default planning must not load spaCy")

    monkeypatch.setattr(LinguisticResourcePool, "pipeline", fail_if_loaded)
    plan = UtterancePlanner(PlannerConfig(language="en-us")).plan("Hello world.")

    assert plan.texts.spoken == "Hello world."
    assert all(token.pos is None and token.tag is None for token in plan.tokens)


def test_spacy_auto_uses_fake_compatible_local_model(monkeypatch):
    loaded_models = []

    class Pipeline:
        def __init__(self):
            self.last_doc = None

        def __call__(self, text):
            self.last_doc = [
                SimpleNamespace(idx=0, text=text, pos_="NOUN", tag_="NN", lemma_=text.lower())
            ]
            return self.last_doc

    pipeline = Pipeline()

    fake_spacy = SimpleNamespace(
        util=SimpleNamespace(get_installed_models=lambda: ["en_core_web_sm"]),
        load=lambda model: loaded_models.append(model) or pipeline,
    )
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)

    analysis = LinguisticResourcePool().analyze(
        "Hello",
        LanguageRun("lang-0", 0, 5, "en-us"),
        PlannerConfig(language="en-us").linguistics.__class__(use_spacy=True),
    )

    assert loaded_models == ["en_core_web_sm"]
    assert analysis.model_name == "en_core_web_sm"
    assert analysis.provider_doc is pipeline.last_doc
    assert analysis.tokens[0].pos == "NOUN"

def _fake_spacy_plan(monkeypatch, *, tag: str = "VBP", morph: str = "Tense=Pres|VerbForm=Fin") -> UtterancePlan:
    class Pipeline:
        def __call__(self, text):
            values = (
                (0, "I", "PRON", "PRP", "I", "Case=Nom"),
                (2, "live", "VERB", tag, "live", morph),
                (7, "here", "ADV", "RB", "here", None),
                (11, ".", "PUNCT", ".", ".", None),
            )
            return [
                SimpleNamespace(
                    idx=idx,
                    text=value,
                    pos_=pos,
                    tag_=token_tag,
                    lemma_=lemma,
                    morph=token_morph,
                )
                for idx, value, pos, token_tag, lemma, token_morph in values
            ]

    monkeypatch.setitem(sys.modules, "spacy", SimpleNamespace(__version__="3.7.0"))
    monkeypatch.setattr(LinguisticResourcePool, "pipeline", lambda self, model, require=False: Pipeline())
    config = PlannerConfig(
        language="en-us",
        text_preparation="identity",
        linguistics=LinguisticsConfig(
            use_spacy=True, spacy_model="fake_model", require_spacy=True
        ),
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
    serialized = plan.to_json()
    assert "provider_doc" not in serialized
    assert "spacy.tokens" not in serialized
    restored = UtterancePlan.from_json(serialized)
    assert restored.tokens == plan.tokens
    assert restored.linguistic_runs == plan.linguistic_runs


def test_fallback_provenance_is_explicit():
    plan = UtterancePlanner(PlannerConfig(language="en-us")).plan("I live here.")
    assert plan.linguistic_runs[0].provider == "fallback"
    assert plan.linguistic_runs[0].model is None
    assert all(token.pos is None and token.tag is None and token.morph is None for token in plan.tokens)


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
