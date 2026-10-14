from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import tomlkit
from renderplan import PausePolicy, PlanningPolicy, RenderProfile, RoleProfile, load_renderplan_set
from renderplan import codec as renderplan_codec

from utterplan import (
    BookCompileRequest,
    BookCompileResult,
    BookRenderRequest,
    BookRenderResult,
    BookServiceError,
    compile_book,
    render_book,
)
from utterplan.config import LinguisticsConfig, PlannerConfig
from utterplan.model import FlowPlan


def _ssmd(text: str) -> str:
    return f'---\nssmd_version: "0.9"\nlanguage: en-US\n---\n{text}\n'


def _book(root: Path, numbers: tuple[int, ...]) -> Path:
    chapters = root / "chapters"
    chapters.mkdir(parents=True)
    entries: list[dict[str, object]] = []
    for number in numbers:
        source = chapters / f"chapter-{number:04d}.ssmd.md"
        source.write_text(_ssmd(f"Chapter {number}."), encoding="utf-8")
        entries.append(
            {
                "id": f"chapter-{number:04d}",
                "source_number": number,
                "path": f"chapters/{source.name}",
                "title": f"Chapter {number}",
            }
        )
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "format": "ssmdconvert.book",
                "schema_version": 1,
                "ssmd_version": "0.9",
                "chapters": entries,
            }
        ),
        encoding="utf-8",
    )
    return root


def _profile(path: Path, voice: str = "amy") -> RenderProfile:
    profile = RenderProfile(
        roles={
            "narrator": RoleProfile(language="en-US", binding={"engine": "test", "voice": voice})
        },
        default_role="narrator",
        planning=PlanningPolicy(split="sentence", capacity_fallback=("token",)),
        pauses=PausePolicy(mode="manual", durations_ms={"sentence": 250}),
    )
    renderplan_codec.save_profile(profile, path)
    return renderplan_codec.load_profile(path)


def test_public_request_and_result_models_are_available_at_package_root() -> None:
    compile_request = BookCompileRequest(Path("book"))
    render_request = BookRenderRequest(Path("book"), Path("profile.renderprofile.toml"))
    compile_result = BookCompileResult(
        workspace=Path("book"),
        chapter_selector="all",
        selected_chapter_ids=(),
        output_dir=Path("book/utterplan"),
        report_path=Path("book/utterplan/compile-report.toml"),
        outcomes=(),
    )
    render_result = BookRenderResult(
        workspace=Path("book"),
        chapter_selector="all",
        profile_path=Path("profile.renderprofile.toml"),
        profile_id="sha256:abc",
        variant="profile--abc",
        variant_dir=Path("book/renderplan/profile--abc"),
        snapshot_path=Path("book/renderplan/profile--abc/renderprofile.toml"),
        set_path=Path("book/renderplan/profile--abc/renderplan-set.toml"),
        report_path=Path("book/renderplan/profile--abc/render-report.toml"),
        selected_chapter_ids=(),
        outcomes=(),
    )
    assert compile_request.book == Path("book")
    assert render_request.profile == Path("profile.renderprofile.toml")
    assert compile_result.exit_code == render_result.exit_code == 0
    assert compile_result.failed == render_result.failed == 0


def test_public_book_services_return_artifact_paths_and_progress(tmp_path: Path) -> None:
    root = _book(tmp_path / "ordered.ssmdbook", (5, 7, 6))
    compile_events = []
    compiled = compile_book(
        root,
        chapters="5-7",
        planner_config=PlannerConfig(
            language="en-US",
            text_preparation="identity",
            linguistics=LinguisticsConfig(use_spacy=False),
        ),
        on_progress=compile_events.append,
    )

    assert compiled.workspace == root
    assert compiled.chapter_selector == "5-7"
    assert compiled.selected_chapter_ids == ("chapter-0005", "chapter-0007", "chapter-0006")
    assert compiled.output_dir == root / "utterplan"
    assert compiled.report_path == root / "utterplan/compile-report.toml"
    assert compiled.failed == 0
    assert compiled.exit_code == 0
    assert tuple(compile_events) == compiled.outcomes
    assert all(FlowPlan.load(outcome.output).schema_version == 7 for outcome in compiled.outcomes)
    compile_report = tomlkit.parse(compiled.report_path.read_text(encoding="utf-8"))
    assert compile_report["requested"] == 3
    assert compile_report["written"] == 3

    profile_path = root / "narration.renderprofile.toml"
    profile = _profile(profile_path)
    render_events = []
    rendered = render_book(
        root,
        profile=profile_path,
        chapters="5-7",
        on_progress=render_events.append,
    )

    assert rendered.workspace == root
    assert rendered.chapter_selector == "5-7"
    assert rendered.selected_chapter_ids == compiled.selected_chapter_ids
    assert rendered.profile_path == profile_path
    assert rendered.profile_id == profile.profile_id
    assert rendered.variant == f"narration--{profile.profile_id.removeprefix('sha256:')[:12]}"
    assert rendered.variant_dir == root / "renderplan" / rendered.variant
    assert rendered.snapshot_path == rendered.variant_dir / "renderprofile.toml"
    assert rendered.set_path == rendered.variant_dir / "renderplan-set.toml"
    assert rendered.report_path == rendered.variant_dir / "render-report.toml"
    assert rendered.failed == 0
    assert rendered.exit_code == 0
    assert tuple(render_events) == rendered.outcomes
    collection = load_renderplan_set(rendered.set_path)
    assert [chapter.id for chapter in collection.chapters] == list(compiled.selected_chapter_ids)
    render_report = tomlkit.parse(rendered.report_path.read_text(encoding="utf-8"))
    assert render_report["requested"] == 3
    assert render_report["written"] == 3


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("all", (5, 7, 6, 11, 13, 12)),
        ("5", (5,)),
        ("5-7", (5, 7, 6)),
        ("5,7,11-13", (5, 7, 11, 13, 12)),
    ],
)
def test_compile_book_selects_original_source_numbers(
    tmp_path: Path, selector: str, expected: tuple[int, ...]
) -> None:
    root = _book(tmp_path / "selection.ssmdbook", (5, 7, 6, 11, 13, 12))
    result = compile_book(
        root,
        chapters=selector,
        planner_config=PlannerConfig(
            language="en-US",
            text_preparation="identity",
            linguistics=LinguisticsConfig(use_spacy=False),
        ),
    )
    assert tuple(int(outcome.id[-4:]) for outcome in result.outcomes) == expected
    assert result.exit_code == 0


def test_public_api_matches_cli_artifacts_and_report_semantics(tmp_path: Path, capsys) -> None:
    from utterplan.cli import main

    selector = "5,7,11-13"
    api_root = _book(tmp_path / "api.ssmdbook", (5, 7, 6, 11, 13, 12))
    cli_root = _book(tmp_path / "cli.ssmdbook", (5, 7, 6, 11, 13, 12))
    config = PlannerConfig(
        language="en-US",
        text_preparation="identity",
        linguistics=LinguisticsConfig(use_spacy=False),
    )
    api_compile = compile_book(api_root, chapters=selector, planner_config=config)
    assert (
        main(
            [
                "compile-book",
                str(cli_root),
                "--chapters",
                selector,
                "--text-preparation",
                "identity",
                "--spacy",
                "off",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert api_compile.selected_chapter_ids == (
        "chapter-0005",
        "chapter-0007",
        "chapter-0011",
        "chapter-0013",
        "chapter-0012",
    )
    api_compile_outputs = [
        (outcome.id, outcome.plan_id, outcome.output.relative_to(api_root))
        for outcome in api_compile.outcomes
    ]
    cli_compile_outputs = [
        (
            chapter_id,
            FlowPlan.load(cli_root / "utterplan" / f"{chapter_id}.utterplan.toml").plan_id,
            Path("utterplan") / f"{chapter_id}.utterplan.toml",
        )
        for chapter_id in api_compile.selected_chapter_ids
    ]
    assert api_compile_outputs == cli_compile_outputs
    api_compile_report = tomlkit.parse(api_compile.report_path.read_text(encoding="utf-8"))
    cli_compile_report = tomlkit.parse(
        (cli_root / "utterplan/compile-report.toml").read_text(encoding="utf-8")
    )
    compile_summary = ("format", "version", "requested", "written", "failed", "skipped", "complete")
    assert tuple(api_compile_report[key] for key in compile_summary) == tuple(
        cli_compile_report[key] for key in compile_summary
    )
    assert [
        (item["id"], item.get("plan_id"), item["status"]) for item in api_compile_report["item"]
    ] == [(item["id"], item.get("plan_id"), item["status"]) for item in cli_compile_report["item"]]

    api_profile_path = api_root / "narration.renderprofile.toml"
    cli_profile_path = cli_root / "narration.renderprofile.toml"
    api_profile = _profile(api_profile_path)
    cli_profile = _profile(cli_profile_path)
    api_render = render_book(api_root, profile=api_profile_path, chapters=selector)
    assert (
        main(
            [
                "render-book",
                str(cli_root),
                "--chapters",
                selector,
                "--profile",
                str(cli_profile_path),
            ]
        )
        == 0
    )
    capsys.readouterr()

    cli_variant_dir = cli_root / "renderplan" / api_render.variant
    assert api_profile.profile_id == cli_profile.profile_id
    assert api_render.variant == f"narration--{api_profile.profile_id.removeprefix('sha256:')[:12]}"
    cli_set_path = cli_variant_dir / "renderplan-set.toml"
    assert api_render.set_path.read_bytes() == cli_set_path.read_bytes()
    api_render_outputs = [
        (
            outcome.id,
            outcome.source_plan_id,
            outcome.render_plan_id,
            outcome.source_plan.relative_to(api_root),
            outcome.output.relative_to(api_render.variant_dir),
        )
        for outcome in api_render.outcomes
    ]
    cli_render_outputs = [
        (
            chapter_id,
            FlowPlan.load(cli_root / "utterplan" / f"{chapter_id}.utterplan.toml").plan_id,
            renderplan_codec.load_plan(cli_variant_dir / f"{chapter_id}.renderplan.toml").plan_id,
            Path("utterplan") / f"{chapter_id}.utterplan.toml",
            Path(f"{chapter_id}.renderplan.toml"),
        )
        for chapter_id in api_render.selected_chapter_ids
    ]
    assert api_render_outputs == cli_render_outputs
    api_render_report = tomlkit.parse(api_render.report_path.read_text(encoding="utf-8"))
    cli_render_report = tomlkit.parse(
        (cli_variant_dir / "render-report.toml").read_text(encoding="utf-8")
    )
    render_summary = (
        "format",
        "version",
        "requested",
        "written",
        "failed",
        "skipped",
        "complete",
        "variant",
        "profile_id",
    )
    assert tuple(api_render_report[key] for key in render_summary) == tuple(
        cli_render_report[key] for key in render_summary
    )
    assert [
        (
            item["id"],
            item["source_number"],
            item["status"],
            item.get("source_plan_id"),
            item.get("render_plan_id"),
        )
        for item in api_render_report["item"]
    ] == [
        (
            item["id"],
            item["source_number"],
            item["status"],
            item.get("source_plan_id"),
            item.get("render_plan_id"),
        )
        for item in cli_render_report["item"]
    ]


def test_package_root_book_api_does_not_import_cli() -> None:
    code = (
        "import sys, utterplan; "
        "names=('BookCompileRequest','BookCompileResult','BookRenderRequest',"
        "'BookRenderResult','compile_book','render_book'); "
        "assert all(hasattr(utterplan, name) for name in names); "
        "assert 'utterplan.cli' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)


def test_render_book_incremental_reuse_and_force(tmp_path: Path) -> None:
    root = _book(tmp_path / "incremental.ssmdbook", (5, 6, 7))
    compile_book(
        root,
        planner_config=PlannerConfig(
            language="en-US",
            text_preparation="identity",
            linguistics=LinguisticsConfig(use_spacy=False),
        ),
    )
    profile_path = root / "narration.renderprofile.toml"
    _profile(profile_path)

    first = render_book(root, profile=profile_path, chapters="5")
    second = render_book(root, profile=profile_path, chapters="6")
    assert first.variant == second.variant
    collection = load_renderplan_set(second.set_path)
    assert [chapter.source_number for chapter in collection.chapters] == [5, 6]

    protected = render_book(root, profile=profile_path, chapters="5")
    assert protected.exit_code == 1
    assert protected.failed == 1
    forced = render_book(root, profile=profile_path, chapters="5", force=True)
    assert forced.exit_code == 0


def test_render_book_refuses_orphan_variant_and_profile_mismatch(tmp_path: Path) -> None:
    root = _book(tmp_path / "orphan.ssmdbook", (5,))
    compile_book(
        root,
        planner_config=PlannerConfig(
            language="en-US",
            text_preparation="identity",
            linguistics=LinguisticsConfig(use_spacy=False),
        ),
    )
    profile_a_path = root / "narration.renderprofile.toml"
    profile_b_path = root / "other.renderprofile.toml"
    profile_a = _profile(profile_a_path)
    profile_b = _profile(profile_b_path, "joe")
    orphan_dir = (
        root / "renderplan" / f"orphan--{profile_a.profile_id.removeprefix('sha256:')[:12]}"
    )
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "scratch.txt").write_text("unindexed", encoding="utf-8")
    with pytest.raises(BookServiceError, match="refusing to adopt non-empty"):
        render_book(root, profile=profile_a_path, variant="orphan")

    source_variant = render_book(root, profile=profile_a_path, variant="shared").variant_dir
    target_variant = (
        root / "renderplan" / f"shared--{profile_b.profile_id.removeprefix('sha256:')[:12]}"
    )
    shutil.copytree(source_variant, target_variant)
    with pytest.raises(BookServiceError, match="does not match the active RenderProfile"):
        render_book(root, profile=profile_b_path, chapters="5", variant="shared")


def test_render_book_refuses_snapshot_identity_mismatch(tmp_path: Path) -> None:
    root = _book(tmp_path / "snapshot.ssmdbook", (5,))
    compile_book(
        root,
        planner_config=PlannerConfig(
            language="en-US",
            text_preparation="identity",
            linguistics=LinguisticsConfig(use_spacy=False),
        ),
    )
    profile_path = root / "narration.renderprofile.toml"
    _profile(profile_path)
    result = render_book(root, profile=profile_path, chapters="5")
    changed_profile = _profile(root / "changed.renderprofile.toml", "joe")
    renderplan_codec.save_profile(changed_profile, result.snapshot_path)

    with pytest.raises(BookServiceError, match="snapshot identity"):
        render_book(root, profile=profile_path, chapters="5")


def test_public_book_services_refuse_outputs_inside_source_chapters(tmp_path: Path) -> None:
    root = _book(tmp_path / "unsafe.ssmdbook", (5,))
    with pytest.raises(BookServiceError, match="inside the source chapters"):
        compile_book(root, output_dir=root / "chapters" / "plans")
    assert not (root / "chapters/plans").exists()

    compile_book(
        root,
        planner_config=PlannerConfig(
            language="en-US",
            text_preparation="identity",
            linguistics=LinguisticsConfig(use_spacy=False),
        ),
    )
    profile_path = root / "narration.renderprofile.toml"
    _profile(profile_path)
    with pytest.raises(BookServiceError, match="inside source chapters"):
        render_book(root, profile=profile_path, output_root=root / "chapters" / "renderplans")
    assert not (root / "chapters/renderplans").exists()
