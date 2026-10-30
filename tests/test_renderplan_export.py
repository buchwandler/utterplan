from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from renderplan import (
    PauseItem,
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
    SegmentDirectives,
    TokenView,
    VoiceDirective,
    build_render_plan,
    compile_document,
)
from utterplan.cli import main
from utterplan.model import PauseIntent
from utterplan.renderplan_pause_timing import PauseTimingConfig
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


def test_public_build_is_deterministic_and_rejects_incomplete_replan_inputs(tmp_path: Path) -> None:
    source = _source()
    profile = _profile()

    first = build_render_plan(source, profile)
    second = build_render_plan(source, profile)

    assert first == second
    assert first.producer is not None and first.producer.name == "utterplan"
    assert first.speech[0].text == "one two three."
    assert first.speech[0].source[0].locator == "f000000.s000"
    assert first.speech[0].wav == "000001.wav"
    renderplan_path = tmp_path / "single-role.renderplan.toml"
    renderplan_codec.save_plan(first, renderplan_path)
    serialized = renderplan_path.read_text(encoding="utf-8")
    loaded = renderplan_codec.load_plan(renderplan_path)
    assert first.schema_version == 2
    assert serialized.count("[bindings.narrator]") == 1
    assert "[flow.binding]" not in serialized
    assert loaded.plan_id == first.plan_id == first.computed_id()
    assert all(
        speech.binding == dict(profile.roles[speech.role].binding) for speech in loaded.speech
    )
    loaded.validate_against_profile(profile)

    changed_role = replace(profile.roles["narrator"], binding={"engine": "changed"})
    changed_profile = replace(profile, roles={"narrator": changed_role}, profile_id=None)
    changed_plan = build_render_plan(source, changed_profile)
    assert changed_plan.speech[0].segment_id != first.speech[0].segment_id
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
    initial_capture = capsys.readouterr()
    initial_output = json.loads(initial_capture.out)
    assert initial_output["pause_timing"] == {
        "mode": "fixed",
        "algorithm": "utterplan.pause-timing.v1",
    }
    assert initial_capture.err == ""
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
                "--pause-timing",
                "engaging",
            ]
        )
        == 2
    )
    assert "--pause-timing applies only to initial RenderPlan projection" in capsys.readouterr().err
    assert not next_path.exists()
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


def _multi_role_source() -> FlowPlan:
    return FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        "Host line.",
                        "en-US",
                        directives=SegmentDirectives(voice=VoiceDirective(reference="host")),
                    ),
                    FlowSegment(
                        "Guest line.",
                        "en-US",
                        directives=SegmentDirectives(voice=VoiceDirective(reference="guest")),
                    ),
                    FlowSegment("Narration line.", "en-US"),
                )
            ),
        ),
    )


def _multi_role_profile(*, include_cast: bool = True) -> RenderProfile:
    roles = {
        "narrator": RoleProfile(language="en-US", binding={"renderer": "kokoro"}),
    }
    if include_cast:
        roles.update(
            {
                "host": RoleProfile(language="en-US", binding={"renderer": "kitten"}),
                "guest": RoleProfile(language="en-US", binding={"renderer": "piper"}),
            }
        )
    return RenderProfile(
        roles=roles,
        default_role="narrator",
        planning=PlanningPolicy(split="sentence"),
        pauses=PausePolicy(mode="manual"),
    )


def test_render_plan_json_reports_role_coverage_metadata(tmp_path: Path, capsys) -> None:
    source_path = tmp_path / "roles.utterplan.toml"
    profile_path = tmp_path / "cast.renderprofile.toml"
    output_path = tmp_path / "roles.renderplan.toml"
    _multi_role_source().save(source_path)
    profile = _multi_role_profile()
    renderplan_codec.save_profile(profile, profile_path)

    assert (
        main(
            [
                "render-plan",
                str(source_path),
                "--profile",
                str(profile_path),
                "--output",
                str(output_path),
                "--json",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["role_coverage"] == {
        "default_role": "narrator",
        "required": ["host", "guest", "narrator"],
        "available": ["guest", "host", "narrator"],
        "missing": [],
        "uses_default_role": True,
    }
    assert output_path.is_file()

    plan = renderplan_codec.load_plan(output_path)
    serialized = output_path.read_text(encoding="utf-8")
    for role in ("narrator", "host", "guest"):
        assert serialized.count(f"[bindings.{role}]") == 1
    assert "[flow.binding]" not in serialized
    assert plan.schema_version == 2
    assert plan.plan_id == plan.computed_id()
    assert all(speech.binding == dict(profile.roles[speech.role].binding) for speech in plan.speech)
    plan.validate_against_profile(profile)
    human_output_path = tmp_path / "roles-human.renderplan.toml"
    assert (
        main(
            [
                "render-plan",
                str(source_path),
                "--profile",
                str(profile_path),
                "--output",
                str(human_output_path),
            ]
        )
        == 0
    )
    human_output = capsys.readouterr()
    assert "roles: host, guest, narrator" in human_output.err
    assert "coverage: complete" in human_output.err
    assert f"wrote {human_output_path}" in human_output.err


def test_render_plan_missing_roles_fail_before_output_creation(tmp_path: Path, capsys) -> None:
    source_path = tmp_path / "roles.utterplan.toml"
    profile_path = tmp_path / "partial.renderprofile.toml"
    output_path = tmp_path / "must-not-exist.renderplan.toml"
    _multi_role_source().save(source_path)
    renderplan_codec.save_profile(_multi_role_profile(include_cast=False), profile_path)

    assert (
        main(
            [
                "render-plan",
                str(source_path),
                "--profile",
                str(profile_path),
                "--output",
                str(output_path),
            ]
        )
        == 1
    )

    assert "host, guest" in capsys.readouterr().err
    assert not output_path.exists()


def test_inspect_roles_reports_source_inventory_without_profile(tmp_path: Path, capsys) -> None:
    source_path = tmp_path / "roles.utterplan.toml"
    _multi_role_source().save(source_path)

    assert main(["inspect", str(source_path), "--roles"]) == 0

    output = capsys.readouterr().out
    assert "host  1 speech segments" in output
    assert "guest  1 speech segments" in output
    assert "required by 1 speech segments" in output


@pytest.mark.parametrize("force", (False, True))
def test_render_plan_stale_profile_is_rejected_before_output(
    tmp_path: Path, capsys, force: bool
) -> None:
    source_path = tmp_path / "chapter.utterplan.toml"
    profile_path = tmp_path / "stale.renderprofile.toml"
    output_path = tmp_path / "chapter.renderplan.toml"
    _source().save(source_path)
    renderplan_codec.save_profile(_profile(), profile_path)
    profile_path.write_text(
        profile_path.read_text(encoding="utf-8").replace(
            'engine = "fixture"', 'engine = "changed"'
        ),
        encoding="utf-8",
    )
    args = [
        "render-plan",
        str(source_path),
        "--profile",
        str(profile_path),
        "--output",
        str(output_path),
    ]
    if force:
        args.append("--force")

    assert main(args) == 1
    error = capsys.readouterr().err
    assert f"invalid RenderProfile {profile_path.resolve()}" in error
    assert "profile_id does not match profile content" in error
    assert "Regenerate or re-save the RenderProfile with its producer" in error
    assert "--force does not bypass profile identity validation" in error
    assert not output_path.exists()


def test_context_timing_changes_only_automatic_pause_duration_and_identity() -> None:
    source = _source()
    profile = _profile()
    fixed = build_render_plan(source, profile)
    natural = build_render_plan(source, profile, pause_timing=PauseTimingConfig("natural"))
    engaging = build_render_plan(source, profile, pause_timing=PauseTimingConfig("engaging"))

    def pause_items(plan):
        return [
            (index, item) for index, item in enumerate(plan.flow) if isinstance(item, PauseItem)
        ]

    fixed_pauses = pause_items(fixed)
    natural_pauses = pause_items(natural)
    engaging_pauses = pause_items(engaging)
    assert len(fixed_pauses) == len(natural_pauses) == len(engaging_pauses) == 1
    assert fixed_pauses[0][0] == natural_pauses[0][0] == engaging_pauses[0][0]
    assert fixed_pauses[0][1].reason == natural_pauses[0][1].reason == engaging_pauses[0][1].reason
    assert fixed_pauses[0][1].duration_ms == 500
    assert natural_pauses[0][1].duration_ms != 500
    assert engaging_pauses[0][1].duration_ms != 500
    assert fixed.speech == natural.speech == engaging.speech
    assert fixed.source_plan_id == natural.source_plan_id == engaging.source_plan_id
    assert fixed.render_profile_id == natural.render_profile_id == engaging.render_profile_id
    assert fixed.plan_id != natural.plan_id != engaging.plan_id
    for plan in (fixed, natural, engaging):
        plan.validate_against_profile(profile)


def test_authored_pause_intents_are_unchanged_by_adaptive_projection() -> None:
    profile = replace(
        _profile(),
        pauses=PausePolicy(mode="manual", durations_ms={"sentence": 500, "strong": 800}),
    )
    intents = (
        PauseIntent("timed", "650ms"),
        PauseIntent("strong"),
        PauseIntent("none"),
    )
    for intent in intents:
        source = FlowPlan(
            language="en-US",
            flow=(
                FlowUnit(
                    (
                        FlowSegment(
                            "one two three.",
                            "en-US",
                            pause_after=intent,
                            boundary_after=("sentence",),
                        ),
                    )
                ),
            ),
        )
        fixed = build_render_plan(source, profile)
        engaging = build_render_plan(source, profile, pause_timing=PauseTimingConfig("engaging"))
        fixed_pause = next(item for item in fixed.flow if isinstance(item, PauseItem))
        engaging_pause = next(item for item in engaging.flow if isinstance(item, PauseItem))
        assert (engaging_pause.duration_ms, engaging_pause.reason) == (
            fixed_pause.duration_ms,
            fixed_pause.reason,
        )


def test_replanning_rejects_explicit_pause_timing() -> None:
    source = _source()
    profile = _profile()
    previous = build_render_plan(source, profile, pause_timing=PauseTimingConfig("engaging"))
    with pytest.raises(RenderPlanProjectionError, match="pause_timing applies only to initial"):
        build_render_plan(
            source,
            profile,
            previous_plan=previous,
            preflight=_preflight(previous, profile),
            pause_timing=PauseTimingConfig("natural"),
        )


def test_boundary_context_uses_complete_group_and_incoming_flow_segment() -> None:
    source = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment("The earlier", "en-US"),
                    FlowSegment(" thought finished.", "en-US", boundary_after=("sentence",)),
                    FlowSegment("And tomorrow.", "en-US"),
                )
            ),
        ),
    )
    profile = _profile()
    fixed = build_render_plan(source, profile)
    engaging = build_render_plan(source, profile, pause_timing=PauseTimingConfig("engaging"))
    fixed_pause = next(item for item in fixed.flow if isinstance(item, PauseItem))
    engaging_pause = next(item for item in engaging.flow if isinstance(item, PauseItem))
    assert fixed.speech[0].text == "The earlier thought finished."
    assert fixed_pause.reason == engaging_pause.reason == "sentence"
    assert engaging_pause.duration_ms < fixed_pause.duration_ms


@pytest.mark.parametrize("mode", ("fixed", "natural", "engaging"))
def test_render_plan_cli_pause_timing_provenance(tmp_path: Path, capsys, mode: str) -> None:
    source_path = tmp_path / "chapter.utterplan.toml"
    profile_path = tmp_path / "voice.renderprofile.toml"
    output_path = tmp_path / f"chapter-{mode}.renderplan.toml"
    human_output_path = tmp_path / f"chapter-{mode}-human.renderplan.toml"
    _source().save(source_path)
    profile = _profile()
    renderplan_codec.save_profile(profile, profile_path)

    assert (
        main(
            [
                "render-plan",
                str(source_path),
                "--profile",
                str(profile_path),
                "--output",
                str(output_path),
                "--pause-timing",
                mode,
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["pause_timing"] == {
        "mode": mode,
        "algorithm": "utterplan.pause-timing.v1",
    }
    plan = renderplan_codec.load_plan(output_path)
    pause = next(item for item in plan.flow if isinstance(item, PauseItem))
    assert pause.duration_ms == 500 if mode == "fixed" else pause.duration_ms != 500

    assert (
        main(
            [
                "render-plan",
                str(source_path),
                "--profile",
                str(profile_path),
                "--output",
                str(human_output_path),
                "--pause-timing",
                mode,
            ]
        )
        == 0
    )
    assert f"pause timing: {mode}" in capsys.readouterr().err
