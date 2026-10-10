from __future__ import annotations

from dataclasses import replace
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.compiler_helpers import CompilerTestPlanner as UtterancePlanner
from utterplan import FlowPlan, PauseIntent, PlannerConfig
from utterplan.cli import _format_for_path, main
from utterplan.exceptions import PlanFormatError
from utterplan.language import language_lookup_key
from utterplan.pauses import boundary_is_active


def _installed_ssmd_version() -> tuple[int, int, int]:
    parts = version("ssmd").split(".")
    return tuple(int(part) for part in parts[:3])  # type: ignore[return-value]


def test_canonical_scene_break_is_structural_not_renderer_text() -> None:
    plan = _planner().plan("Before.\n\n...p\n\nAfter.")

    assert plan.texts.structural == "Before.\n\nAfter."
    assert all("...p" not in segment.text for segment in plan.segments)


@pytest.mark.skipif(
    _installed_ssmd_version() < (0, 9, 3),
    reason="legacy horizontal-rule scene breaks require SSMD 0.9.3",
)
def test_legacy_scene_break_is_structural_not_renderer_text() -> None:
    plan = _planner().plan("Before.\n\n---\n\nAfter.")

    assert plan.texts.structural == "Before.\n\nAfter."
    assert all(segment.text != "---" for segment in plan.segments)


@pytest.mark.parametrize(
    ("body", "scene_break_count"),
    [
        ("Before.\n\n---\n\nAfter.", 1),
        ("Before.\n\n---\n\nMiddle.\n\n---\n\nAfter.", 2),
        ("Before.\n\n...p\n\nAfter.", 1),
        ("---\n\nAfter.\n\n---", 2),
        ("Before --- after.", 0),
        ("Before.\n\n\\---\n\nAfter.", 0),
    ],
)
def test_front_matter_scene_breaks_are_boundaries_not_renderer_text(
    body: str, scene_break_count: int
) -> None:
    source = f'---\nssmd_version: "0.9"\ntitle: Demo\n---\n{body}'
    if "\\---" in body:
        attempt = _planner().compile_attempt(source)
        assert attempt.status == "blocked"
        plan = attempt.candidate
    else:
        plan = _planner().plan(source)

    scene_breaks = [
        event
        for event in plan.boundaries
        if event.kind == "explicit"
        and (
            event.attrs.get("semantic") == "scene_break"
            or event.attrs.get("legacy_horizontal_rule")
            or (event.origin == "ssmd" and event.strength == "x-strong")
        )
    ]
    assert len(scene_breaks) == scene_break_count
    if scene_break_count:
        assert "---" not in plan.texts.structural or body.startswith("---")
        assert all(segment.text.strip() != "---" for segment in plan.segments)
        assert plan.document_metadata["planning"]["renderability"]["guaranteed"] is True
    elif "Before --- after." in body:
        assert "Before --- after." in plan.texts.structural
        assert any("---" in segment.text for segment in plan.segments)
    elif "\\---" in body:
        assert "---" in plan.texts.structural
        assert any(segment.text == "---" for segment in plan.segments)
        assert any(
            issue.code == "renderability.punctuation_only" for issue in attempt.renderability.issues
        )


def test_legacy_parser_front_matter_scene_break_uses_clean_to_source_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ssmd

    from utterplan.parsers import SSMDDocumentParser, map_structural_span_to_source

    header = '---\nssmd_version: "0.9"\ntitle: Demo\n---\n'
    body = "Before.\n\n---\n\nAfter."
    source = header + body
    legacy_result = SimpleNamespace(
        clean_text=body,
        annotations=[],
        events=[],
        header={"ssmd_version": "0.9", "title": "Demo"},
        warnings=[],
        diagnostics=[],
        text_spans=[
            SimpleNamespace(
                char_start=0,
                char_end=len(body),
                source_start=len(header),
                source_end=len(source),
            )
        ],
    )
    monkeypatch.setattr(ssmd, "parse_structure", lambda *args, **kwargs: legacy_result)

    parsed = SSMDDocumentParser().parse(source, _planner().config)
    assert parsed.structural_text == "Before.\n\nAfter."
    source_after = source.index("After.")
    assert map_structural_span_to_source(
        parsed, len("Before.\n\n"), len(parsed.structural_text)
    ) == (source_after, source_after + len("After."))
    scene = next(event for event in parsed.boundaries if event.attrs.get("legacy_horizontal_rule"))
    assert scene.attrs["source_start"] == source.index("---", len(header))
    assert scene.attrs["source_end"] == source_after

    plan = _planner().plan(source)
    assert [segment.text for segment in plan.segments] == ["Before.", "After."]


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


@pytest.mark.parametrize(
    ("break_time", "expected"),
    [("200ms", PauseIntent("timed", "200ms")), ("0ms", PauseIntent("timed", "0ms"))],
)
def test_explicit_ssmd_break_precedes_sentence_default(
    break_time: str, expected: PauseIntent
) -> None:
    source = f"""---
ssmd_version: "0.9"
pause_defaults:
  sentence: 800ms
---
One. ...{break_time} Two."""
    plan = _planner().plan(source)

    explicit = next(event for event in plan.boundaries if event.kind == "explicit")
    first_segment = plan.segments[0]
    assert first_segment.pause_after == expected
    assert explicit.attrs["time"] == break_time
    assert explicit.seconds is None


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
Hello [there.]{lang="en-GB"}
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
    restored = type(plan).from_dict(payload)
    assert restored.annotations == plan.annotations


def test_heading_events_are_preserved_but_inactive_for_pause_resolution() -> None:
    plan = _planner().plan("# Main\n\n## Sub\n\nText.")
    headings = [event for event in plan.boundaries if event.kind == "heading"]

    assert [event.attrs["level"] for event in headings] == ["1", "2"]
    assert all(event.attrs["structural_only"] for event in headings)
    assert all(not boundary_is_active(event, _planner().config.pauses) for event in headings)


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
    plan = FlowPlan.from_toml(capsys.readouterr().out)
    assert plan.document.format == "ssmd"


def test_cli_auto_detection_keeps_ordinary_markdown_plain(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "ordinary.md"
    source.write_text("# Ordinary Markdown", encoding="utf-8")
    assert main(["compile", str(source), "--lang", "en-us", "--text-preparation", "identity"]) == 0
    plan = FlowPlan.from_toml(capsys.readouterr().out)
    assert plan.document.format == "plain"


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


def test_zero_width_audio_annotation_is_preserved() -> None:
    uri = "sfx:impact.knock?seed=42"
    plan = _planner().plan(f'Before. []{{src="{uri}" desc="Knock"}} After.')

    audio_annotations = [item for item in plan.annotations if item.attrs.get("src") == uri]

    assert len(audio_annotations) == 1
    annotation = audio_annotations[0]
    assert annotation.structural_start == annotation.structural_end
    assert annotation.spoken_start == annotation.spoken_end


def test_zero_width_non_media_annotation_is_not_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ssmd

    from utterplan.parsers import SSMDDocumentParser

    parsed = SimpleNamespace(
        clean_text="",
        annotations=[
            SimpleNamespace(
                kind="emphasis",
                attrs={"tag": "emphasis"},
                char_start=0,
                char_end=0,
            )
        ],
        events=[],
        header={},
        warnings=[],
        diagnostics=[],
    )
    monkeypatch.setattr(ssmd, "parse_structure", lambda *args, **kwargs: parsed)

    result = SSMDDocumentParser().parse("", _planner().config)

    assert result.annotations == ()


def test_sequence_fallback_mode_roundtrips_and_is_part_of_plan_identity() -> None:
    source = '---\nssmd_version: "0.9"\nsequence_fallback_mode: preserve\n---\nHello.'
    plan = _planner().plan(source)

    restored = type(plan).from_dict(plan.to_dict())
    assert restored.document_metadata["sequence_fallback_mode"] == "preserve"
    assert FlowPlan.from_toml(_planner().compile(source).plan.to_toml()).schema_version == 5

    changed_policy = replace(
        plan,
        document_metadata={**plan.document_metadata, "sequence_fallback_mode": "spell"},
    ).with_identity()
    assert changed_policy.plan_id != plan.plan_id
