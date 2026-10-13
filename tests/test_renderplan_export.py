from __future__ import annotations

import json
from pathlib import Path

from renderplan import (
    PausePolicy,
    PlanningPolicy,
    PreflightCheck,
    PreflightReport,
    RenderProfile,
    ReplanRequest,
    RoleProfile,
)
from renderplan import codec as renderplan_codec

from utterplan import (
    FlowPlan,
    FlowSegment,
    FlowUnit,
    LinguisticsConfig,
    PlannerConfig,
    TokenView,
    build_render_plan,
    compile_document,
)
from utterplan.cli import main
from utterplan.renderplan_projection import RenderPlanProjectionError


def _profile() -> RenderProfile:
    return RenderProfile(
        roles={"narrator": RoleProfile(language="en-US", binding={"engine": "fixture"})},
        default_role="narrator",
        planning=PlanningPolicy(split="sentence", capacity_fallback=("token",)),
        pauses=PausePolicy(mode="manual", durations_ms={"sentence": 500}),
    )


def _source() -> FlowPlan:
    return FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        "one two three.",
                        "en-US",
                        tokens=(TokenView(0, 3), TokenView(4, 7), TokenView(8, 13)),
                        boundary_after=("sentence",),
                    ),
                )
            ),
        ),
    )


def _preflight(plan, profile) -> PreflightReport:
    speech = plan.speech[0]
    segment_id = speech.segment_id or speech.computed_id()
    return PreflightReport(
        render_plan_id=plan.plan_id or plan.computed_id(),
        source_plan_id=plan.source_plan_id,
        render_profile_id=profile.profile_id or profile.computed_id(),
        status="replan",
        checks=(
            PreflightCheck(
                segment_number=speech.number,
                segment_id=segment_id,
                status="too_long",
                metric="model_tokens",
                measured=700,
                maximum=512,
                source="fixture-renderer",
            ),
        ),
        replan=(
            ReplanRequest(
                segment_number=speech.number,
                segment_id=segment_id,
                source=speech.source,
                current_level=speech.planning_level,
                metric="model_tokens",
                measured=700,
                maximum=512,
            ),
        ),
    ).with_identity()


def test_public_build_is_deterministic_and_rejects_incomplete_replan_inputs() -> None:
    source = _source()
    profile = _profile()

    first = build_render_plan(source, profile)
    second = build_render_plan(source, profile)

    assert first == second
    assert first.producer is not None and first.producer.name == "utterplan"
    assert first.speech[0].text == "one two three."
    assert first.speech[0].source[0].locator == "f000000.s000"
    assert first.speech[0].wav == "000001.wav"
    try:
        build_render_plan(source, profile, preflight=_preflight(first, profile))
    except RenderPlanProjectionError as error:
        assert error.code == "renderplan.replan.inputs"
    else:
        raise AssertionError("preflight without previous plan must fail closed")


def test_render_plan_cli_initial_json_replan_and_explain(tmp_path: Path, capsys) -> None:
    source = _source()
    profile = _profile()
    source_path = tmp_path / "chapter.utterplan.toml"
    profile_path = tmp_path / "voice.renderprofile.toml"
    initial_path = tmp_path / "chapter.renderplan.toml"
    next_path = tmp_path / "chapter.next.renderplan.toml"
    preflight_path = tmp_path / "chapter.preflight.toml"
    source.save(source_path)
    renderplan_codec.save_profile(profile, profile_path)

    assert (
        main(
            [
                "render-plan",
                str(source_path),
                "--profile",
                str(profile_path),
                "--output",
                str(initial_path),
                "--json",
            ]
        )
        == 0
    )
    initial_output = json.loads(capsys.readouterr().out)
    previous = renderplan_codec.load_plan(initial_path)
    assert initial_output["plan"]["plan_id"] == previous.plan_id

    report = _preflight(previous, profile)
    renderplan_codec.save_preflight(report, preflight_path)
    assert (
        main(
            [
                "render-plan",
                str(source_path),
                "--profile",
                str(profile_path),
                "--previous",
                str(initial_path),
                "--preflight",
                str(preflight_path),
                "--output",
                str(next_path),
                "--explain",
            ]
        )
        == 0
    )
    explanation = capsys.readouterr().out
    replanned = renderplan_codec.load_plan(next_path)
    assert replanned.plan_id != previous.plan_id
    assert [speech.planning_level for speech in replanned.speech] == ["token", "token"]
    assert "replaced previous speech 1" in explanation
    assert "model_tokens 700 > 512" in explanation
    assert "fallback sentence -> token" in explanation
    assert "children: 1, 2" in explanation
    assert "pause-after: 0ms capacity" in explanation


def test_render_plan_cli_rejects_mutated_source_before_writing_output(
    tmp_path: Path, capsys
) -> None:
    original = _source()
    profile = _profile()
    previous = build_render_plan(original, profile)
    report = _preflight(previous, profile)
    source_path = tmp_path / "chapter.utterplan.toml"
    profile_path = tmp_path / "voice.renderprofile.toml"
    previous_path = tmp_path / "previous.renderplan.toml"
    preflight_path = tmp_path / "preflight.toml"
    output_path = tmp_path / "should-not-exist.renderplan.toml"
    mutated = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        "one two four.",
                        "en-US",
                        tokens=(TokenView(0, 3), TokenView(4, 7), TokenView(8, 12)),
                        boundary_after=("sentence",),
                    ),
                )
            ),
        ),
    )
    mutated.save(source_path)
    renderplan_codec.save_profile(profile, profile_path)
    renderplan_codec.save_plan(previous, previous_path)
    renderplan_codec.save_preflight(report, preflight_path)

    result = main(
        [
            "render-plan",
            str(source_path),
            "--profile",
            str(profile_path),
            "--previous",
            str(previous_path),
            "--preflight",
            str(preflight_path),
            "--output",
            str(output_path),
        ]
    )

    assert result == 1
    assert "renderplan.replan.source_plan_id" in capsys.readouterr().err
    assert not output_path.exists()


def test_repository_ssmd_fixture_compiles_and_projects() -> None:
    fixture = Path(__file__).parent / "fixtures" / "canonical_consumer_contract.ssmd"
    compiled = compile_document(
        fixture.read_text(encoding="utf-8"),
        input_format="ssmd",
        config=PlannerConfig(language="en-GB", linguistics=LinguisticsConfig(use_spacy=False)),
    )
    profile = RenderProfile(
        roles={"narrator": RoleProfile(language="en-GB", binding={"engine": "fixture"})},
        default_role="narrator",
        planning=PlanningPolicy(split="sentence"),
        pauses=PausePolicy(mode="manual"),
    )

    projected = build_render_plan(compiled.plan, profile)

    assert projected.speech
    assert [speech.text for speech in projected.speech] == ["Hello.", "Next."]
    assert any(control.name == "prosody" for control in projected.speech[0].controls)


def test_render_plan_cli_requires_previous_and_preflight_as_a_pair(tmp_path: Path, capsys) -> None:
    source_path = tmp_path / "chapter.utterplan.toml"
    profile_path = tmp_path / "voice.renderprofile.toml"
    source_path.write_text(_source().to_toml(), encoding="utf-8")
    renderplan_codec.save_profile(_profile(), profile_path)

    result = main(
        [
            "render-plan",
            str(source_path),
            "--profile",
            str(profile_path),
            "--preflight",
            str(tmp_path / "missing.preflight.toml"),
            "--output",
            str(tmp_path / "out.renderplan.toml"),
        ]
    )

    assert result == 2
    assert "--previous and --preflight must be supplied together" in capsys.readouterr().err
