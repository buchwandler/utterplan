from __future__ import annotations

from dataclasses import fields, replace
from types import SimpleNamespace

import pytest
import ttsready

from utterplan.exceptions import TextPreparationError
from utterplan.language import LanguageRun
from utterplan.linguistics import RunAnalysis
from utterplan.model import AnnotationSpan, TokenAnnotation
from utterplan.preparation import TTSReadyTextPreparer


def _runs_and_analyses(text: str) -> tuple[tuple[LanguageRun, ...], tuple[RunAnalysis, ...]]:
    split = text.index("Bonjour")
    runs = (
        LanguageRun("en-run", 0, split, "en-us"),
        LanguageRun("fr-run", split, len(text), "fr"),
    )
    english_doc = object()
    french_doc = object()
    analyses = (
        RunAnalysis(
            language="en-us",
            start=0,
            end=split,
            tokens=(
                TokenAnnotation(0, 4, "Live", pos="VERB", tag="VB", lemma="live", language="en-us"),
                TokenAnnotation(5, 8, "ART", pos="NOUN", tag="NN", lemma="art", language="en-us"),
                TokenAnnotation(9, 10, "5", pos="NUM", lemma="5", language="en-us"),
                TokenAnnotation(11, 13, "kg", pos="NOUN", lemma="kg", language="en-us"),
            ),
            provider_doc=english_doc,
        ),
        RunAnalysis(
            language="fr",
            start=split,
            end=len(text),
            tokens=(TokenAnnotation(split, len(text), "Bonjour.", lemma="bonjour", language="fr"),),
            provider_doc=french_doc,
        ),
    )
    return runs, analyses


def test_adapter_builds_explicit_profile_and_always_preserves_run_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    prepare_run = ttsready.prepare_run

    def spy(text: str, **kwargs: object):
        calls.append((text, kwargs))
        return prepare_run(text, **kwargs)

    monkeypatch.setattr(ttsready, "prepare_run", spy)
    text = "Live ART 5 kg Bonjour."
    runs, analyses = _runs_and_analyses(text)
    result = TTSReadyTextPreparer(sequence_fallback_mode="preserve").prepare(
        text, "en-us", runs, analyses=analyses
    )

    assert result.spoken_text
    assert [local_text for local_text, _ in calls] == [
        text[run.spoken_start : run.spoken_end] for run in runs
    ]
    for _local_text, kwargs in calls:
        profile = kwargs["profile"]
        assert {field.name: getattr(profile, field.name) for field in fields(profile)} == {
            "use_spacy": False,
            "symbol_mode": "none",
            "normalize_unicode": True,
            "normalize_whitespace": True,
            "strip_outer_whitespace": False,
            "collapse_horizontal_whitespace": True,
            "normalize_line_whitespace": True,
            "collapse_blank_lines": True,
            "generic_acronym_mode": "known_only",
            "sequence_fallback_mode": "preserve",
            "expand_abbreviations": True,
            "expand_structured": True,
            "expand_numbers": True,
        }
        assert kwargs["preserve_run_boundaries"] is True
        assert kwargs["strict"] is False
        assert kwargs["unit_id"] in {"en-run", "fr-run"}


def test_adapter_localizes_provider_neutral_tokens_and_protects_ssmd_spans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    prepare_run = ttsready.prepare_run

    def spy(text: str, **kwargs: object):
        calls.append((text, kwargs))
        return prepare_run(text, **kwargs)

    monkeypatch.setattr(ttsready, "prepare_run", spy)
    text = "Live ART 5 kg Bonjour."
    runs, analyses = _runs_and_analyses(text)
    annotation = AnnotationSpan(
        id="pronunciation-1",
        kind="pronunciation",
        attrs={"ph": "ɑːrt"},
        structural_start=5,
        structural_end=8,
        source_start=5,
        source_end=8,
    )

    TTSReadyTextPreparer().prepare(text, "en-us", runs, (annotation,), analyses=analyses)

    first_tokens = calls[0][1]["linguistic_tokens"]
    assert [
        (token.start, token.end, token.text, token.pos, token.tag, token.lemma, token.language)
        for token in first_tokens
    ] == [
        (0, 4, "Live", "VERB", "VB", "live", "en-us"),
        (5, 8, "ART", "NOUN", "NN", "art", "en-us"),
        (9, 10, "5", "NUM", None, "5", "en-us"),
        (11, 13, "kg", "NOUN", None, "kg", "en-us"),
    ]
    second_token = calls[1][1]["linguistic_tokens"][0]
    assert (second_token.start, second_token.end, second_token.text, second_token.language) == (
        0,
        len("Bonjour."),
        "Bonjour.",
        "fr",
    )
    protected = calls[0][1]["protected_spans"]
    assert [(span.start, span.end, span.reason) for span in protected] == [
        (5, 8, "ssmd.speech-directive")
    ]
    assert calls[1][1]["protected_spans"] == ()
    assert all("nlp" not in kwargs for _, kwargs in calls)


def test_adapter_concatenates_exact_maps_rebases_changes_and_preserves_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    prepare_run = ttsready.prepare_run

    def spy(text: str, **kwargs: object):
        result = prepare_run(text, **kwargs)
        calls.append(result)
        return result

    monkeypatch.setattr(ttsready, "prepare_run", spy)
    monkeypatch.setattr(
        ttsready,
        "runtime_versions",
        lambda: {"ttsready": "0.2.2", "spokenform": "0.4.5"},
    )
    text = "Hello Bonjour 5 kg."
    runs = (
        LanguageRun("en-run", 0, len("Hello "), "en-us"),
        LanguageRun("fr-run", len("Hello "), len(text), "fr"),
    )
    result = TTSReadyTextPreparer().prepare(text, "en-us", runs)

    expected_map = ttsready.SourceOutputMap.concatenate(item.source_map for item in calls)
    assert result.source_map.source_length == len(text)
    assert result.source_map.output_length == len(result.spoken_text)
    for start, end in ((0, 0), (0, 5), (6, 11), (len(text), len(text))):
        assert result.source_map.map_source_span(start, end) == expected_map.map_source_span(
            start, end
        )
    assert result.info.backend == "spokenform"
    assert result.info.version == "0.4.5"
    assert result.info.languages == ("en-us", "fr")
    assert result.info.replacements
    assert [item["source_start"] for item in result.info.replacements] == sorted(
        item["source_start"] for item in result.info.replacements
    )
    replacement = next(item for item in result.info.replacements if item["source"] == "5 kg")
    assert replacement["source_start"] == text.index("5 kg")
    assert (
        result.spoken_text[replacement["output_start"] : replacement["output_end"]]
        == "cinq kilogrammes"
    )
    assert set(replacement) <= {
        "source_start",
        "source_end",
        "output_start",
        "output_end",
        "source",
        "replacement",
        "kind",
        "rule",
        "language",
    }


def test_adapter_translates_ttsready_errors_and_rejects_bad_maps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = LanguageRun("run", 0, 3, "en-us")
    preparer = TTSReadyTextPreparer()

    def fail(*_args: object, **_kwargs: object):
        raise ttsready.TTSReadyError("backend failure")

    monkeypatch.setattr(ttsready, "prepare_run", fail)
    with pytest.raises(TextPreparationError, match="backend failure") as error:
        preparer.prepare("abc", "en-us", (run,))
    assert isinstance(error.value.__cause__, ttsready.TTSReadyError)

    malformed = SimpleNamespace(
        source_text="abc",
        spoken_text="xyz",
        changes=(),
        warnings=(),
        source_map=SimpleNamespace(source_length=4, output_length=3),
    )
    monkeypatch.setattr(ttsready, "prepare_run", lambda *_args, **_kwargs: malformed)
    with pytest.raises(TextPreparationError, match="source map length"):
        preparer.prepare("abc", "en-us", (run,))

    malformed.source_map = SimpleNamespace(source_length=3, output_length=2)
    with pytest.raises(TextPreparationError, match="output map length"):
        preparer.prepare("abc", "en-us", (run,))


def test_adapter_rejects_mismatched_analysis_and_tokens_before_prepare_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def spy(*_args: object, **_kwargs: object):
        nonlocal calls
        calls += 1
        return ttsready.prepare_run(*_args, **_kwargs)

    monkeypatch.setattr(ttsready, "prepare_run", spy)
    run = LanguageRun("run", 0, 4, "en-us")
    mismatched = RunAnalysis("fr", 0, 4, (), provider_doc=object())
    with pytest.raises(TextPreparationError, match="does not match"):
        TTSReadyTextPreparer().prepare("text", "en-us", (run,), analyses=(mismatched,))
    assert calls == 0

    crossing = RunAnalysis("en-us", 0, 4, (TokenAnnotation(3, 5, "xt", language="en-us"),))
    with pytest.raises(TextPreparationError, match="falls outside"):
        TTSReadyTextPreparer().prepare("text", "en-us", (run,), analyses=(crossing,))
    assert calls == 0


def test_adapter_keeps_ttsready_warnings_as_strings(monkeypatch: pytest.MonkeyPatch) -> None:
    prepare_run = ttsready.prepare_run

    def with_warning(text: str, **kwargs: object):
        result = prepare_run(text, **kwargs)
        return SimpleNamespace(
            source_text=result.source_text,
            spoken_text=result.spoken_text,
            changes=result.changes,
            issues=result.issues,
            source_map=result.source_map,
            warnings=("adapter warning",),
        )

    monkeypatch.setattr(ttsready, "prepare_run", with_warning)
    run = LanguageRun("run", 0, 6, "en-us")
    result = TTSReadyTextPreparer().prepare("Hello.", "en-us", (run,))

    assert result.info.warnings == ("adapter warning",)



def test_adapter_preserves_backend_per_change_language_provenance() -> None:
    text = "Dr. bought 5 kg."
    run = LanguageRun("run", 0, len(text), "en-us")

    result = TTSReadyTextPreparer().prepare(text, "en-us", (run,))

    assert [(change["source"], change["language"]) for change in result.info.replacements] == [
        ("Dr.", "en_US"),
        ("5 kg", "en"),
    ]



def test_adapter_does_not_invent_language_when_change_language_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_run = ttsready.prepare_run

    def without_change_language(text: str, **kwargs: object):
        result = prepare_run(text, **kwargs)
        return SimpleNamespace(
            source_text=result.source_text,
            spoken_text=result.spoken_text,
            changes=tuple(replace(change, language=None) for change in result.changes),
            warnings=result.warnings,
            source_map=result.source_map,
        )

    monkeypatch.setattr(ttsready, "prepare_run", without_change_language)
    text = "Dr."
    run = LanguageRun("run", 0, len(text), "en-us")
    result = TTSReadyTextPreparer().prepare(text, "en-us", (run,))

    assert result.info.replacements
    assert "language" not in result.info.replacements[0]
