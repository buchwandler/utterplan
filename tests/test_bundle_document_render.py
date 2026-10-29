from __future__ import annotations

import json
import shutil
from pathlib import Path

from renderplan import PausePolicy, PlanningPolicy, RenderProfile, RoleProfile
from renderplan import codec as renderplan_codec

from utterplan._document_service import _compile_document_service, _render_document_service
from utterplan.config import LinguisticsConfig, PlannerConfig
from utterplan.model import FlowPlan, FlowSegment, FlowUnit, SegmentDirectives, VoiceDirective

FIXTURE = Path(__file__).parent / "fixtures/document-bundle-v1/story.ssmd-bundle"


def test_render_document_bundle_projects_canonical_flowplan_without_book_index(
    tmp_path: Path,
) -> None:
    root = tmp_path / "story.ssmd-bundle"
    shutil.copytree(FIXTURE, root)
    source = root / "document.ssmd.md"
    source.write_text(
        '---\nssmd_version: "0.9"\nlanguage: en-US\n---\nHello there.\n', encoding="utf-8"
    )
    _compile_document_service(
        root,
        planner_config=PlannerConfig(
            language="en-US",
            text_preparation="identity",
            linguistics=LinguisticsConfig(use_spacy=False),
        ),
    )
    profile_path = tmp_path / "narration.renderprofile.toml"
    profile = RenderProfile(
        roles={
            "narrator": RoleProfile(language="en-US", binding={"engine": "test", "voice": "amy"})
        },
        default_role="narrator",
        planning=PlanningPolicy(split="sentence", capacity_fallback=("token",)),
        pauses=PausePolicy(mode="manual", durations_ms={"sentence": 250}),
    )
    renderplan_codec.save_profile(profile, profile_path)
    result = _render_document_service(root, profile=profile_path)
    assert result.source_plan_path == root / "utterplan" / "document.utterplan.toml"
    assert result.variant_dir.parent == root / "renderplan"
    assert result.renderplan_path.name == "document.renderplan.toml"
    plan = renderplan_codec.load_plan(result.renderplan_path)
    plan.validate_against_profile(profile)
    serialized = result.renderplan_path.read_text(encoding="utf-8")
    assert plan.schema_version == 2
    assert serialized.count("[bindings.narrator]") == 1
    assert "[flow.binding]" not in serialized
    assert plan.plan_id == plan.computed_id()
    assert all(speech.binding == dict(profile.roles[speech.role].binding) for speech in plan.speech)
    flow = FlowPlan.load(result.source_plan_path)
    assert result.variant.startswith("narration--")
    assert result.snapshot_path.is_file()
    assert result.report_path.is_file()
    assert plan.source_plan_id == flow.plan_id
    assert plan.render_profile_id == result.profile_id
    assert not (result.variant_dir / "renderplan-set.toml").exists()
    assert source.read_text(encoding="utf-8").startswith("---")
    assert (
        json.loads((root / "manifest.json").read_text(encoding="utf-8"))["format"]
        == "ssmdconvert.document"
    )


def test_render_document_bundle_returns_multi_role_coverage_and_bindings(tmp_path: Path) -> None:
    root = tmp_path / "multi-role.ssmd-bundle"
    shutil.copytree(FIXTURE, root)
    (root / "document.ssmd.md").write_text(
        '---\nssmd_version: "0.9"\nlanguage: en-US\n---\nHost, guest, and narrator.\n',
        encoding="utf-8",
    )
    _compile_document_service(
        root,
        planner_config=PlannerConfig(
            language="en-US",
            text_preparation="identity",
            linguistics=LinguisticsConfig(use_spacy=False),
        ),
    )
    source_plan_path = root / "utterplan" / "document.utterplan.toml"
    FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        "Host.",
                        "en-US",
                        directives=SegmentDirectives(voice=VoiceDirective(reference="host")),
                    ),
                    FlowSegment(
                        "Guest.",
                        "en-US",
                        directives=SegmentDirectives(voice=VoiceDirective(reference="guest")),
                    ),
                    FlowSegment("Narrator.", "en-US"),
                )
            ),
        ),
    ).save(source_plan_path)

    profile_path = tmp_path / "multi-role.renderprofile.toml"
    profile = RenderProfile(
        roles={
            "narrator": RoleProfile(language="en-US", binding={"engine": "kokoro"}),
            "host": RoleProfile(language="en-US", binding={"engine": "kitten"}),
            "guest": RoleProfile(language="en-US", binding={"engine": "piper"}),
        },
        default_role="narrator",
        planning=PlanningPolicy(split="sentence"),
        pauses=PausePolicy(mode="manual"),
    )
    renderplan_codec.save_profile(profile, profile_path)

    result = _render_document_service(root, profile=profile_path)

    assert result.required_roles == ("host", "guest", "narrator")
    assert result.available_roles == ("guest", "host", "narrator")
    assert result.uses_default_role is True
    plan = renderplan_codec.load_plan(result.renderplan_path)
    assert {speech.role for speech in plan.speech} == {"host", "guest", "narrator"}
    assert {speech.binding["engine"] for speech in plan.speech} == {"kokoro", "kitten", "piper"}
    serialized = result.renderplan_path.read_text(encoding="utf-8")
    for role in ("narrator", "host", "guest"):
        assert serialized.count(f"[bindings.{role}]") == 1
    assert "[flow.binding]" not in serialized
    assert plan.schema_version == 2
    assert plan.plan_id == plan.computed_id()
    assert all(speech.binding == dict(profile.roles[speech.role].binding) for speech in plan.speech)
    plan.validate_against_profile(profile)
