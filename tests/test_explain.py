from __future__ import annotations

from pathlib import Path

from utterplan import PlannerConfig, UtterancePlan, UtterancePlanner
from utterplan.explain import format_explanation

GOLDEN = Path("tests/golden")


def _load(name: str) -> UtterancePlan:
    return UtterancePlan.load(GOLDEN / name)


def test_basic_explanation_is_human_oriented_and_exact() -> None:
    output = format_explanation(_load("basic_en.utterplan.json"))

    assert output == (
        "UtterPlan explanation\n\n"
        "Plan\n"
        "  input: plain\n"
        "  default language: en-us\n"
        "  preparation: spokenform, no replacements\n"
        "  pause mode: tts\n"
        "  grouping: paragraph\n"
        "  result: 1 unit, 1 segment\n\n"
        "Text preparation\n"
        "  No written-to-spoken changes.\n\n"
        "Speech plan\n"
        "  Unit 1: paragraph\n"
        '    1. [en-us] "Hello."\n\n'
        "No warnings.\n"
    )
    assert "sha256:" not in output
    assert "token-0" not in output
    assert "spoken 0:6" not in output


def test_preparation_replacements_are_explained_without_ranges_by_default() -> None:
    plan = _load("spokenform_offsets.utterplan.json")
    output = format_explanation(plan)

    assert '"Dr." -> "Doctor"  (abbreviation: abbr:Dr.)' in output
    assert '"5 kg" -> "five kilograms"  (structured: en.quantity)' in output
    assert '"Jan. 4" -> "January fourth"  (structured: en.date.mdy_text)' in output
    assert "structural 0:3" not in output

    details = format_explanation(plan, details=True)
    assert "structural 0:3 -> spoken 0:6" in details
    assert "structural 17:21 -> spoken 20:34" in details


def test_parenthetical_pauses_use_resolved_pause_and_boundary_provenance() -> None:
    output = format_explanation(_load("parenthetical.utterplan.json"))

    assert output.count("pause 0.15 s") == 2
    assert "before: pause 0.15 s: parenthetical opening, detected by phrasplit" in output
    assert "before: pause 0.15 s: parenthetical closing, detected by phrasplit" in output
    assert "split because" not in output


def test_explicit_pause_uses_resolved_segment_duration() -> None:
    output = format_explanation(_load("ssmd_breaks.utterplan.json"))

    assert "after: pause 0.50 s: explicit boundary, from SSMD" in output
    assert "after: pause 0.15 s: explicit boundary, from SSMD" in output


def test_directives_are_humanized() -> None:
    output = format_explanation(_load("directives.utterplan.json"))

    assert "effective prosody: rate 1.2, pitch +2st, volume 80%" in output
    assert "emphasis: strong" in output
    assert "{'prosody'" not in output


def test_ssmd_explanation_summarizes_semantics_and_metadata() -> None:
    output = format_explanation(_load("ssmd_09_comprehensive.utterplan.json"), details=True)

    assert "SSMD version: 0.9" in output
    assert 'title: "Renderer-neutral SSMD 0.9 contract"' in output
    assert "document language: sr-Latn" in output
    assert "voice: reference=narrator, name=Mira" in output
    assert "effective prosody: rate fast, pitch high, volume soft" in output
    assert "say-as: date, format dd.mm.yyyy, detail 1" in output
    assert 'substitution: "water"' in output
    assert 'description "door chime"' in output
    assert "repeat count 1.5, level -3dB" in output
    assert "extension refs: acme.effects.whisper" in output
    assert "heading level 1 at spoken" in output


def test_ssmd_warning_diagnostic_includes_source_location() -> None:
    text = """---
ssmd_version: "0.9"
unknown: true
---
Hello."""
    plan = UtterancePlanner(PlannerConfig(language="en-us", document_format="ssmd")).plan(text)

    output = format_explanation(plan)

    assert "header.unknown_key [warn]" in output
    assert "source " in output
    assert "line 3, column 1" in output


def test_multilingual_segments_are_in_render_order() -> None:
    output = format_explanation(_load("multilingual.utterplan.json"))

    labels = [output.index(label) for label in ("[en-us]", "[fr]", "[en-us]")]
    assert labels[0] < labels[1]
    assert '[fr] "Bonjour"' in output
    assert '[en-us] "."' in output


def test_markers_are_shown_in_their_owning_unit() -> None:
    output = format_explanation(_load("markers.utterplan.json"))

    assert "Unit 2: sentence" in output
    assert "markers: @mark" in output
    assert output.index("Unit 2: sentence") < output.index("markers: @mark")


def test_details_include_technical_identity_and_correlated_ids() -> None:
    output = format_explanation(_load("parenthetical.utterplan.json"), details=True)

    assert "plan id: sha256:" in output
    assert "schema: 3" in output
    assert "id: seg-000001" in output
    assert "spoken: 19:53" in output
    assert "content hash: sha256:" in output
    assert "events: boundary-000000" in output
    assert "origin phrasplit" in output
    assert "planning.complete [info]" in output
    assert "analysis: provider=fallback" in output
    assert "lemma=the" in output
    assert "pos=-" in output
    assert "tag=-" in output
    assert "morph=-" in output


def test_explanation_is_deterministic() -> None:
    plan = _load("directives.utterplan.json")

    assert format_explanation(plan) == format_explanation(plan)
    assert format_explanation(plan, details=True) == format_explanation(plan, details=True)


def test_empty_collections_are_concise() -> None:
    output = format_explanation(_load("basic_en.utterplan.json"))

    assert "No written-to-spoken changes." in output
    assert "No warnings." in output
    assert "Warnings\n" not in output
    assert "Language runs" not in output
    assert "markers:" not in output
    assert "Boundaries" not in output
