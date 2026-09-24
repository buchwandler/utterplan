from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

from utterplan import PlannerConfig, UtterancePlanner
from utterplan.cli import _format_for_path, main
from utterplan.exceptions import PlanFormatError
from utterplan.format import schema
from utterplan.language import language_lookup_key
from utterplan.pauses import boundary_is_active


def _planner() -> UtterancePlanner:
    return UtterancePlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
            text_preparation="identity",
        )
    )


def test_ssmd_09_parser_uses_strict_dialect_for_unversioned_fragments() -> None:
    with pytest.raises(PlanFormatError) as error:
        _planner().plan('[Hello]{volume="loud", rate="fast"}')

    assert error.value.code == "syntax.comma_separator_legacy"


@pytest.mark.parametrize(("break_time", "expected_seconds"), [("200ms", 0.2), ("0ms", 0.0)])
def test_explicit_ssmd_break_precedes_sentence_default(
    break_time: str, expected_seconds: float
) -> None:
    source = f"""---
ssmd_version: "0.9"
pause_defaults:
  sentence: 800ms
---
One. ...{break_time} Two."""
    plan = _planner().plan(source)

    explicit = next(event for event in plan.boundaries if event.kind == "explicit")
    sentence = next(event for event in plan.boundaries if event.kind == "sentence")
    first_segment = plan.segments[0]
    assert first_segment.pause_after.seconds == pytest.approx(expected_seconds)
    assert first_segment.pause_after.events == tuple(sorted((explicit.id, sentence.id)))


@pytest.mark.parametrize(
    ("source", "code"),
    [
        ('[x]{lang="no_such_tag!!"}', "language.invalid_tag"),
        ('[x]{gender="banana"}', "voice.invalid_gender"),
        ('[x]{age="-1" voice="v"}', "voice.invalid_age"),
        ('[x]{variant="0" voice="v"}', "voice.invalid_variant"),
        ('[x]{src="x.wav" repeat="0"}', "audio.invalid_repeat_count"),
        ('[x]{volume="banana"}', "prosody.invalid_volume"),
        ('[x]{rate="banana"}', "prosody.invalid_rate"),
        ('[x]{pitch="banana"}', "prosody.invalid_pitch"),
        (
            """---
ssmd_version: "0.8"
---
Hello.""",
            "header.version_unsupported",
        ),
    ],
)
def test_ssmd_errors_preserve_stable_codes(source: str, code: str) -> None:
    with pytest.raises(PlanFormatError) as error:
        _planner().plan(source)

    assert error.value.code == code
    assert error.value.path == "$.source"


def test_ssmd_front_matter_is_preserved_and_sets_document_language() -> None:
    text = """---
ssmd_version: "0.9"
title: Demo
language: sr-Latn
voice_bindings:
  host: provider-a
voice_defaults:
  host:
    rate: slow
pause_defaults:
  paragraph: 450ms
prosody_transitions:
  enabled: true
  same_voice_only: true
  rate: 100ms
language_detection:
  mode: auto
  languages: [sr-Latn, en-GB]
requires:
  extensions: [acme.effects.whisper]
---
Hello [there]{lang="en-GB"}.
"""
    plan = _planner().plan(text)

    assert plan.document_metadata["header"]["language"] == "sr-Latn"
    assert plan.document_metadata["voice_defaults"]["host"]["rate"] == "slow"
    assert plan.document_metadata["requires"]["extensions"] == ["acme.effects.whisper"]
    assert {run.language for run in plan.languages} == {"sr-Latn", "en-GB"}
    assert not any("unknown SSMD header" in warning for warning in plan.warnings)


def test_authored_language_tags_are_preserved_while_lookup_keys_normalize() -> None:
    plan = _planner().plan(
        '---\nssmd_version: "0.9"\nlanguage: sr-Latn\n---\nHello [there]{lang="en-GB"} world.'
    )

    assert {run.language for run in plan.languages} == {"sr-Latn", "en-GB"}
    assert language_lookup_key("EN_GB") == "en-gb"
    assert {segment.language for segment in plan.segments} == {"sr-Latn", "en-GB"}


def test_ssmd_annotation_source_provenance_roundtrips_in_schema_v3() -> None:
    source = '[Hello]{voice-name="Joanna"}'
    plan = _planner().plan(source)
    annotation = plan.annotations[0]

    assert annotation.source_start == 0
    assert annotation.source_end == len(source)
    payload = plan.to_dict()
    jsonschema.validate(payload, schema())
    restored = type(plan).from_dict(payload)
    assert restored.annotations == plan.annotations


def test_heading_events_are_preserved_but_inactive_for_pause_resolution() -> None:
    plan = _planner().plan("# Main\n\n## Sub\n\nText.")
    headings = [event for event in plan.boundaries if event.kind == "heading"]

    assert [event.attrs["level"] for event in headings] == ["1", "2"]
    assert all(event.attrs["structural_only"] for event in headings)
    assert all(not boundary_is_active(event, _planner().config.pauses) for event in headings)
    heading_ids = {event.id for event in headings}
    assert all(
        heading_ids.isdisjoint(segment.pause_before.events + segment.pause_after.events)
        for segment in plan.segments
    )


def test_cli_auto_detection_recognizes_ssmd_names_and_versioned_markdown(tmp_path: Path) -> None:
    assert _format_for_path(tmp_path / "chapter.ssmd", "Hello") == "ssmd"
    assert _format_for_path(tmp_path / "chapter.ssmd.md", "Hello") == "ssmd"
    assert (
        _format_for_path(tmp_path / "chapter.md", '---\nssmd_version: "9.9"\n---\nText') == "ssmd"
    )
    assert _format_for_path(tmp_path / "ordinary.md", "# Plain Markdown") == "plain"


def test_cli_compiles_versioned_markdown_as_ssmd(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "chapter.md"
    source.write_text(
        """---
ssmd_version: "0.9"
---
[Hello]{voice-name="Joanna"}""",
        encoding="utf-8",
    )
    assert main(["compile", str(source), "--lang", "en-us", "--text-preparation", "identity"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source"]["format"] == "ssmd"


def test_cli_auto_detection_keeps_ordinary_markdown_plain(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "ordinary.md"
    source.write_text("# Ordinary Markdown", encoding="utf-8")
    assert main(["compile", str(source), "--lang", "en-us", "--text-preparation", "identity"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source"]["format"] == "plain"


def test_parser_warnings_retain_structured_source_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ssmd

    warning = SimpleNamespace(
        code="example.warning",
        message="Example warning",
        severity="warning",
        source_start=2,
        source_end=5,
        line=1,
        column=3,
        hint="Check this span",
    )
    parsed = SimpleNamespace(
        clean_text="Hello.",
        annotations=[],
        events=[],
        header={},
        warnings=["Example warning"],
        diagnostics=[warning],
    )
    monkeypatch.setattr(ssmd, "parse_structure", lambda *args, **kwargs: parsed)

    plan = _planner().plan("Hello.")
    diagnostic = next(item for item in plan.diagnostics if item.code == "example.warning")

    assert diagnostic.source_start == 2
    assert diagnostic.source_end == 5
    assert diagnostic.line == 1
    assert diagnostic.column == 3
    assert diagnostic.hint == "Check this span"
    assert diagnostic.to_dict()["source_start"] == 2
