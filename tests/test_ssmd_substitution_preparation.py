from __future__ import annotations

from typing import Any, Literal

import pytest
import ttsready

from tests.compiler_helpers import CompilerTestPlanner
from utterplan import PlannerConfig
from utterplan.exceptions import ConfigurationError, PlanFormatError
from utterplan.flow_projection import project_compiler_plan
from utterplan.language import LanguageRun
from utterplan.model import AnnotationSpan, BoundaryEvent
from utterplan.preparation import SSMDSubstitutionPreparer


def _planner(
    *,
    mode: Literal["auto", "ssmd", "spokenform", "identity"] = "auto",
    document_format: Literal["plain", "ssmd"] = "ssmd",
) -> CompilerTestPlanner:
    return CompilerTestPlanner(
        PlannerConfig(
            language="en-us",
            document_format=document_format,
            text_preparation=mode,
        )
    )


@pytest.mark.parametrize(
    ("source", "written", "spoken"),
    [
        ('[ART]{sub="A R T"}', "ART", "A R T"),
        ('[.02]{sub="point zero two"}', ".02", "point zero two"),
        ('[3–2–1]{sub="three - two - one"}', "3–2–1", "three - two - one"),
    ],
)
def test_ssmd_mode_applies_authored_alias_once_with_exact_provenance(
    source: str, written: str, spoken: str
) -> None:
    plan = _planner().plan(source)

    assert plan.texts.structural == written
    assert plan.texts.spoken == spoken
    assert len(plan.preparation.replacements) == 1
    replacement = plan.preparation.replacements[0]
    assert replacement["source"] == written
    assert replacement["replacement"] == spoken
    assert replacement["kind"] == "ssmd-sub"
    assert replacement["rule"] == "ssmd.sub"
    assert replacement["annotation_id"]
    assert plan.segments[0].text == spoken
    assert plan.segments[0].directives.substitution is None


def test_ssmd_mode_does_not_expand_unannotated_text_and_legacy_mode_remains_opt_in() -> None:
    source = '[H2O]{sub="water"} ordinary 5 kg.'

    authoritative = _planner().plan(source)
    legacy = _planner(mode="spokenform").plan(source)

    assert authoritative.texts.spoken == "water ordinary 5 kg."
    assert authoritative.preparation.backend == "ssmd"
    assert authoritative.document_metadata["text_preparation_mode"] == "ssmd"
    assert any(item.code == "preparation.mode_resolved" for item in authoritative.diagnostics)
    assert legacy.texts.spoken == "H2O ordinary five kilograms."
    assert legacy.preparation.backend == "spokenform"
    assert legacy.segments[0].directives.substitution.alias == "water"
    assert any(item.code == "preparation.legacy_spokenform_on_ssmd" for item in legacy.diagnostics)


def test_ssmd_compilation_never_calls_ttsready_or_spokenform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args, **kwargs):
        raise AssertionError("SSMD-authoritative preparation must not call TTSReady/Spokenform")

    monkeypatch.setattr(ttsready, "prepare_run", fail)
    monkeypatch.setattr(ttsready, "prepare_units", fail)

    plan = _planner().plan('[ART]{sub="A R T"} and 5 kg')
    assert plan.texts.spoken == "A R T and 5 kg"


def test_ssmd_mode_rejects_plain_input() -> None:
    with pytest.raises(ConfigurationError, match="requires SSMD input"):
        _planner(mode="ssmd", document_format="plain").plan("plain words")


def test_plain_auto_keeps_spokenform_default() -> None:
    plan = _planner(document_format="plain").plan("5 kg")
    assert plan.texts.spoken == "five kilograms"
    assert plan.document_metadata["text_preparation_mode"] == "spokenform"


def test_ssmd_source_map_is_bidirectional_monotone_and_bias_aware() -> None:
    text = "abc .02 xyz"
    annotation = AnnotationSpan(
        "sub-1", "sub", {"sub": "point zero two"}, 4, 7, source_start=10, source_end=30
    )
    run = LanguageRun("lang-0", 0, len(text), "en-us")
    at_start = BoundaryEvent("before", 4, "explicit", attrs={"anchor": "before"})
    at_end = BoundaryEvent("after", 7, "explicit", attrs={"anchor": "after"})

    prepared = SSMDSubstitutionPreparer().prepare(
        text, "en-us", (run,), (annotation,), (at_start, at_end)
    )
    source_map: Any = prepared.source_map
    record = prepared.info.replacements[0]
    output_start, output_end = record["output_start"], record["output_end"]

    assert prepared.spoken_text == "abc point zero two xyz"
    assert source_map.map_source_span(4, 7) == (output_start, output_end)
    assert source_map.map_output_span(output_start, output_end) == (4, 7)
    assert source_map.map_source_position(5, bias="left") == output_start
    assert source_map.map_source_position(5, bias="right") == output_end
    assert [source_map.map_source_position(i) for i in range(len(text) + 1)] == sorted(
        source_map.map_source_position(i) for i in range(len(text) + 1)
    )
    assert [
        source_map.map_output_position(i) for i in range(len(prepared.spoken_text) + 1)
    ] == sorted(source_map.map_output_position(i) for i in range(len(prepared.spoken_text) + 1))
    assert prepared.boundaries[0].position == output_start
    assert prepared.boundaries[1].position == output_end
    assert (prepared.annotations[0].spoken_start, prepared.annotations[0].spoken_end) == (
        output_start,
        output_end,
    )
    replay = text[:4] + record["replacement"] + text[7:]
    assert replay == prepared.spoken_text


def test_explicit_break_inside_substitution_is_precise_error() -> None:
    annotation = AnnotationSpan(
        "sub-1", "sub", {"sub": "A R T"}, 0, 3, source_start=2, source_end=20
    )
    boundary = BoundaryEvent("pause-1", 1, "explicit", attrs={"anchor": "after"})

    with pytest.raises(PlanFormatError) as error:
        SSMDSubstitutionPreparer().prepare(
            "ART", "en-us", (LanguageRun("lang-0", 0, 3, "en-us"),), (annotation,), (boundary,)
        )
    assert error.value.code == "preparation.ssmd_sub_invalid"
    assert "structural range [0:3)" in str(error.value)
    assert "SSMD source range [2:20)" in str(error.value)


def test_substitution_conflicting_with_pronunciation_is_rejected() -> None:
    substitution = AnnotationSpan("sub-1", "sub", {"sub": "A R T"}, 0, 3)
    pronunciation = AnnotationSpan("ph-1", "phoneme", {"ph": "art"}, 0, 3)

    with pytest.raises(PlanFormatError, match="overlaps incompatible annotation ph-1"):
        SSMDSubstitutionPreparer().prepare(
            "ART", "en-us", (LanguageRun("lang-0", 0, 3, "en-us"),), (substitution, pronunciation)
        )


def test_nested_emphasis_substitution_preserves_whitespace_and_local_provenance() -> None:
    source = (
        'Three said, *Target [Null+1]{sub="Null plus one"} on approach*, '
        "and included the direction vectors."
    )
    plan = _planner().plan(source)
    expected = "Three said, Target Null plus one on approach, and included the direction vectors."

    assert plan.texts.spoken == expected
    assert "TargetNull" not in plan.texts.spoken
    emphasized = [
        segment
        for segment in plan.segments
        if segment.text.startswith("Target Null plus one on approach")
    ]
    assert len(emphasized) == 1
    assert emphasized[0].text == "Target Null plus one on approach, "
    assert emphasized[0].directives.emphasis is not None

    flow = project_compiler_plan(plan)
    replacement_segments = [
        (segment, replacement)
        for unit in flow.flow
        for segment in unit.segments
        for replacement in segment.replacements
    ]
    assert len(replacement_segments) == 1
    segment, replacement = replacement_segments[0]
    assert replacement.source == "Null+1"
    assert replacement.surface(segment.text) == "Null plus one"
    assert 0 < replacement.start < replacement.end < len(segment.text)
    assert not any(
        diagnostic.code == "segmentation.token_reanalyzed" for diagnostic in plan.diagnostics
    )


def test_substitution_span_with_unproven_edge_whitespace_fails_safely() -> None:
    annotation = AnnotationSpan("sub-1", "sub", {"sub": "spoken"}, 0, 4)

    with pytest.raises(PlanFormatError) as error:
        SSMDSubstitutionPreparer().prepare(
            " ART", "en-us", (LanguageRun("lang-0", 0, 4, "en-us"),), (annotation,)
        )

    assert error.value.code == "preparation.ssmd_sub_span_ambiguous"


def test_segmentation_diagnostic_offsets_slice_raw_ssmd_source() -> None:
    source = "Tar*get* is here."
    plan = _planner().plan(source)
    diagnostic = next(
        item for item in plan.diagnostics if item.code == "segmentation.token_reanalyzed"
    )

    assert diagnostic.source_start is not None
    assert diagnostic.source_end is not None
    assert source[diagnostic.source_start : diagnostic.source_end] == "Tar*get"
