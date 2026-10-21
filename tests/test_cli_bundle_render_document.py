from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import tomlkit
from renderplan import PausePolicy, PlanningPolicy, RenderProfile, RoleProfile
from renderplan import codec as renderplan_codec

from utterplan.cli import main
from utterplan.model import FlowPlan, FlowSegment, FlowUnit, SegmentDirectives, VoiceDirective

FIXTURE = Path(__file__).parent / "fixtures/document-bundle-v1/story.ssmd-bundle"
SSMD = '---\nssmd_version: "0.9"\nlanguage: en-US\n---\n\nHello there.\n'


def _workspace(tmp_path: Path, *, compile_plan: bool = True) -> Path:
    root = tmp_path / "workspace.ssmd-bundle"
    shutil.copytree(FIXTURE, root)
    (root / "document.ssmd.md").write_text(SSMD, encoding="utf-8")
    if compile_plan:
        result = main(
            [
                "bundle",
                "compile",
                str(root),
                "--text-preparation",
                "identity",
                "--spacy",
                "off",
            ]
        )
        assert result == 0
    return root


def _profile(path: Path, *, voice: str = "amy") -> RenderProfile:
    profile = RenderProfile(
        roles={
            "narrator": RoleProfile(language="en-US", binding={"engine": "test", "voice": voice})
        },
        default_role="narrator",
        planning=PlanningPolicy(split="sentence", capacity_fallback=("token",)),
        pauses=PausePolicy(mode="manual", durations_ms={"sentence": 250}),
    )
    renderplan_codec.save_profile(profile, path)
    return profile


def _multi_role_plan() -> FlowPlan:
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


def _multi_role_profile(path: Path, *, include_cast: bool) -> RenderProfile:
    roles = {
        "narrator": RoleProfile(language="en-US", binding={"engine": "test-narrator"}),
    }
    if include_cast:
        roles.update(
            {
                "host": RoleProfile(language="en-US", binding={"engine": "test-host"}),
                "guest": RoleProfile(language="en-US", binding={"engine": "test-guest"}),
            }
        )
    profile = RenderProfile(
        roles=roles,
        default_role="narrator",
        planning=PlanningPolicy(split="sentence"),
        pauses=PausePolicy(mode="manual"),
    )
    renderplan_codec.save_profile(profile, path)
    return profile


def _variant_dir(root: Path, profile_path: Path, *, label: str = "narration") -> Path:
    profile = renderplan_codec.load_profile(profile_path)
    profile_id = profile.profile_id or profile.computed_id()
    return root / "renderplan" / f"{label}--{profile_id.removeprefix('sha256:')[:12]}"


def _render(root: Path, profile_path: Path, *options: str) -> int:
    return main(["bundle", "render", str(root), "--profile", str(profile_path), *options])


def test_render_document_writes_profile_specific_direct_variant_and_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _workspace(tmp_path)
    source_plan = root / "utterplan" / "document.utterplan.toml"
    source_plan_before = source_plan.read_bytes()
    profile_path = tmp_path / "narration.renderprofile.toml"
    profile = _profile(profile_path)

    assert _render(root, profile_path) == 0
    capsys.readouterr()

    variant_dir = _variant_dir(root, profile_path)
    renderplan_path = variant_dir / "document.renderplan.toml"
    snapshot_path = variant_dir / "renderprofile.toml"
    report_path = variant_dir / "render-report.toml"
    assert {path.name for path in variant_dir.iterdir()} == {
        "document.renderplan.toml",
        "renderprofile.toml",
        "render-report.toml",
    }
    assert renderplan_path.is_file()
    assert snapshot_path.is_file()
    assert report_path.is_file()
    assert not (root / "renderplan-set.toml").exists()
    plan = renderplan_codec.load_plan(renderplan_path)
    plan.validate_against_profile(profile)
    assert plan.source_plan_id == FlowPlan.load(source_plan).plan_id
    assert (
        renderplan_codec.load_profile(snapshot_path).profile_id
        == renderplan_codec.load_profile(profile_path).profile_id
    )
    report = tomlkit.parse(report_path.read_text(encoding="utf-8"))
    assert report["format"] == "utterplan.render-bundle-report"
    assert report["status"] == "ok"
    assert report["source_plan_id"] == plan.source_plan_id
    assert report["render_plan_id"] == plan.plan_id
    assert source_plan.read_bytes() == source_plan_before
    assert {path.name for path in root.iterdir()} == {
        "manifest.json",
        "document.ssmd.md",
        "utterplan",
        "renderplan",
    }


def test_missing_utterplan_fails_actionably_without_partial_variant(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _workspace(tmp_path, compile_plan=False)
    profile_path = tmp_path / "narration.renderprofile.toml"
    _profile(profile_path)

    assert _render(root, profile_path) == 2
    captured = capsys.readouterr()
    assert "No UtterPlan found at" in captured.err
    assert "utterplan bundle compile" in captured.err
    assert not (root / "renderplan").exists()


def test_distinct_profiles_coexist_and_same_profile_reuses_variant(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _workspace(tmp_path)
    first_profile = tmp_path / "narration.renderprofile.toml"
    second_profile = tmp_path / "alternate.renderprofile.toml"
    _profile(first_profile, voice="amy")
    _profile(second_profile, voice="joe")
    first_variant = _variant_dir(root, first_profile)
    second_variant = _variant_dir(root, second_profile, label="alternate")

    assert first_variant != second_variant
    assert _render(root, first_profile) == 0
    capsys.readouterr()
    snapshot_before = (first_variant / "renderprofile.toml").read_bytes()
    assert _render(root, first_profile, "--force") == 0
    capsys.readouterr()
    assert (first_variant / "renderprofile.toml").read_bytes() == snapshot_before
    assert _render(root, second_profile) == 0
    capsys.readouterr()
    assert (first_variant / "document.renderplan.toml").is_file()
    assert (second_variant / "document.renderplan.toml").is_file()


def test_mismatched_profile_snapshot_is_rejected_even_with_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _workspace(tmp_path)
    profile_path = tmp_path / "narration.renderprofile.toml"
    other_profile_path = tmp_path / "other.renderprofile.toml"
    _profile(profile_path, voice="amy")
    _profile(other_profile_path, voice="joe")
    variant_dir = _variant_dir(root, profile_path)
    assert _render(root, profile_path) == 0
    capsys.readouterr()
    renderplan_path = variant_dir / "document.renderplan.toml"
    previous_plan = renderplan_path.read_bytes()
    renderplan_codec.save_profile(
        renderplan_codec.load_profile(other_profile_path), variant_dir / "renderprofile.toml"
    )

    assert _render(root, profile_path, "--force") == 2
    captured = capsys.readouterr()
    assert "different profile identity" in captured.err
    assert renderplan_path.read_bytes() == previous_plan


def test_nonempty_variant_without_snapshot_is_never_adopted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _workspace(tmp_path)
    profile_path = tmp_path / "narration.renderprofile.toml"
    _profile(profile_path)
    variant_dir = _variant_dir(root, profile_path)
    variant_dir.mkdir(parents=True)
    state = variant_dir / "state.toml"
    state.write_text("keep = true\n", encoding="utf-8")

    assert _render(root, profile_path, "--force") == 2
    captured = capsys.readouterr()
    assert "unknown non-empty variant directory" in captured.err
    assert state.read_text(encoding="utf-8") == "keep = true\n"
    assert not (variant_dir / "renderprofile.toml").exists()
    assert not (variant_dir / "document.renderplan.toml").exists()


def test_custom_variant_and_output_root_keep_identity_fingerprint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _workspace(tmp_path)
    profile_path = tmp_path / "narration.renderprofile.toml"
    _profile(profile_path)
    output_root = tmp_path / "custom-render-output"
    report_path = tmp_path / "custom-render-report.toml"

    assert (
        _render(
            root,
            profile_path,
            "--variant",
            "warm",
            "--output-root",
            str(output_root),
            "--report",
            str(report_path),
        )
        == 0
    )
    capsys.readouterr()
    profile_id = renderplan_codec.load_profile(profile_path).profile_id
    assert profile_id is not None
    variant_dir = output_root / f"warm--{profile_id.removeprefix('sha256:')[:12]}"
    assert variant_dir.is_dir()
    assert (variant_dir / "document.renderplan.toml").is_file()
    assert report_path.is_file()
    assert not (variant_dir / "render-report.toml").exists()
    assert not (root / "renderplan").exists()


def test_unsafe_variant_labels_are_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _workspace(tmp_path)
    profile_path = tmp_path / "narration.renderprofile.toml"
    _profile(profile_path)

    for label in ("../escape", "nested/name", "nested\\name", ".."):
        assert _render(root, profile_path, "--variant", label) == 2
        captured = capsys.readouterr()
        assert "must not contain path separators or traversal" in captured.err
    assert not (root / "renderplan").exists()


def test_failed_projection_does_not_initialize_variant(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    profile_path = tmp_path / "narration.renderprofile.toml"
    _profile(profile_path)

    def fail_projection(*_args: object, **_kwargs: object) -> None:
        raise ValueError("projection failed")

    monkeypatch.setattr("utterplan._document_service.build_render_plan", fail_projection)

    assert _render(root, profile_path) == 2
    captured = capsys.readouterr()
    assert "projection failed" in captured.err
    assert not (root / "renderplan").exists()


def test_bundle_render_reports_complete_multi_role_coverage(tmp_path: Path, capsys) -> None:
    root = _workspace(tmp_path)
    source_plan = root / "utterplan" / "document.utterplan.toml"
    _multi_role_plan().save(source_plan)
    profile_path = tmp_path / "cast.renderprofile.toml"
    _multi_role_profile(profile_path, include_cast=True)

    assert _render(root, profile_path) == 0

    output = capsys.readouterr().err
    assert "roles:      host, guest, narrator" in output
    assert "coverage:   complete" in output
    renderplan_path = _variant_dir(root, profile_path, label="cast") / "document.renderplan.toml"
    plan = renderplan_codec.load_plan(renderplan_path)
    assert {speech.role for speech in plan.speech} == {"host", "guest", "narrator"}
    assert {speech.binding["engine"] for speech in plan.speech} == {
        "test-host",
        "test-guest",
        "test-narrator",
    }


def test_render_document_missing_role_fails_before_variant_creation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _workspace(tmp_path)
    source_plan = root / "utterplan" / "document.utterplan.toml"
    _multi_role_plan().save(source_plan)
    profile_path = tmp_path / "partial.renderprofile.toml"
    _multi_role_profile(profile_path, include_cast=False)

    assert _render(root, profile_path) == 2

    assert "host, guest" in capsys.readouterr().err
    assert not (root / "renderplan").exists()


def test_document_bundle_render_rejects_non_all_selector(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _workspace(tmp_path)
    profile_path = tmp_path / "voice.renderprofile.toml"
    _profile(profile_path)

    result = _render(root, profile_path, "--chapters", "1")
    captured = capsys.readouterr()

    assert result == 2
    assert "document bundles only support --chapters all" in captured.err
    assert not (root / "renderplan").exists()
