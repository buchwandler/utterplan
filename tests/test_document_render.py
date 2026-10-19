from __future__ import annotations

import json
import shutil
from pathlib import Path

from renderplan import PausePolicy, PlanningPolicy, RenderProfile, RoleProfile
from renderplan import codec as renderplan_codec

from utterplan.config import LinguisticsConfig, PlannerConfig
from utterplan.document_workspace import compile_ssmdoc, render_ssmdoc
from utterplan.model import FlowPlan

FIXTURE = Path(__file__).parent / "fixtures/ssmdoc-v1/story.ssmdoc"


def test_render_ssmdoc_projects_canonical_flowplan_without_book_index(tmp_path: Path) -> None:
    root = tmp_path / "story.ssmdoc"
    shutil.copytree(FIXTURE, root)
    source = root / "document.ssmd.md"
    source.write_text('---\nssmd_version: "0.9"\nlanguage: en-US\n---\nHello there.\n', encoding="utf-8")
    compile_ssmdoc(root, planner_config=PlannerConfig(
        language="en-US", text_preparation="identity",
        linguistics=LinguisticsConfig(use_spacy=False),
    ))
    profile_path = tmp_path / "narration.renderprofile.toml"
    profile = RenderProfile(
        roles={"narrator": RoleProfile(language="en-US", binding={"engine": "test", "voice": "amy"})},
        default_role="narrator", planning=PlanningPolicy(split="sentence", capacity_fallback=("token",)),
        pauses=PausePolicy(mode="manual", durations_ms={"sentence": 250}),
    )
    renderplan_codec.save_profile(profile, profile_path)
    result = render_ssmdoc(root, profile=profile_path)
    assert result.source_plan_path == root / "utterplan" / "document.utterplan.toml"
    assert result.variant_dir.parent == root / "renderplan"
    assert result.renderplan_path.name == "document.renderplan.toml"
    plan = renderplan_codec.load_plan(result.renderplan_path)
    plan.validate_against_profile(profile)
    flow = FlowPlan.load(result.source_plan_path)
    assert result.variant.startswith("narration--")
    assert result.snapshot_path.is_file()
    assert result.report_path.is_file()
    assert plan.source_plan_id == flow.plan_id
    assert plan.render_profile_id == result.profile_id
    assert not (result.variant_dir / "renderplan-set.toml").exists()
    assert source.read_text(encoding="utf-8").startswith("---")
    assert json.loads((root / "manifest.json").read_text(encoding="utf-8"))["format"] == "ssmdconvert.document"
