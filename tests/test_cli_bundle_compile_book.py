from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import tomlkit

import utterplan.batch as batch_module
from utterplan import Diagnostic, FlowPlan, FlowSegment, FlowUnit
from utterplan.cli import build_parser, main
from utterplan.compiler import CompileResult


def _ssmd(text: str) -> str:
    return f'---\nssmd_version: "0.9"\nlanguage: en-US\n---\n{text}\n'


def _write_book(
    root: Path,
    numbers: tuple[int, ...],
    *,
    contents: dict[int, str] | None = None,
    paths: dict[int, str] | None = None,
) -> tuple[Path, list[dict[str, object]]]:
    (root / "chapters").mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    contents = contents or {}
    paths = paths or {}
    for number in numbers:
        relative_path = paths.get(number, f"chapters/chapter-{number:04d}.ssmd.md")
        source_path = root / relative_path
        if number in contents:
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text(contents[number], encoding="utf-8")
        entries.append(
            {
                "id": f"chapter-{number:04d}",
                "source_number": number,
                "path": relative_path,
                "title": f"Chapter {number}",
                "sha256": "0" * 64,
            }
        )
    manifest = {
        "format": "ssmdconvert.book",
        "schema_version": 1,
        "ssmd_version": "0.9",
        "chapters": entries,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return root, entries


def _report(path: Path) -> dict[str, object]:
    return dict(tomlkit.parse(path.read_text(encoding="utf-8")))


def _plan_text(path: Path) -> str:
    plan = FlowPlan.load(path)
    assert plan.schema_version == 7
    return " ".join(segment.text for unit in plan.flow for segment in unit.segments)


@pytest.mark.parametrize(
    ("verbosity", "show_info", "show_warning"),
    [("warnings", False, True), ("all", True, True), ("none", False, False)],
)
def test_compile_book_diagnostic_verbosity_keeps_full_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    verbosity: str,
    show_info: bool,
    show_warning: bool,
) -> None:
    root = tmp_path / f"diagnostics-{verbosity}.ssmd-bundle"
    _write_book(root, (5,), contents={5: _ssmd("A sentence.")})
    plan = FlowPlan(
        language="en-US",
        flow=(FlowUnit((FlowSegment("A sentence.", "en-US"),)),),
    )
    diagnostics = (
        Diagnostic("segmentation.token_reanalyzed", "token reanalyzed", severity="info"),
        Diagnostic(
            "segmentation.token_metadata_degraded",
            "token metadata degraded",
            severity="warning",
            source_start=2,
            source_end=5,
        ),
    )
    monkeypatch.setattr(
        batch_module,
        "compile_document",
        lambda *_args, **_kwargs: CompileResult(
            plan=plan, diagnostics=diagnostics, preparation_mode="ssmd"
        ),
    )

    result = main(["bundle", "compile", str(root), "--chapters", "5", "--diagnostics", verbosity])
    captured = capsys.readouterr()
    assert result == 0
    assert ("segmentation.token_reanalyzed" in captured.err) is show_info
    assert ("segmentation.token_metadata_degraded" in captured.err) is show_warning
    if verbosity == "all":
        assert "info: 1" in captured.err
        assert "warnings: 1" in captured.err
    elif verbosity == "warnings":
        assert "warnings: 1" in captured.err
    else:
        assert "warnings: 1" not in captured.err

    item = _report(root / "utterplan/compile-report.toml")["item"][0]
    assert item["diagnostic_count"] == 2
    assert item["info_count"] == 1
    assert item["warning_count"] == 1
    assert item["renderability_repair_count"] == 0
    assert {diagnostic["code"] for diagnostic in item["diagnostics"]} == {
        "segmentation.token_reanalyzed",
        "segmentation.token_metadata_degraded",
    }


def test_compile_book_root_range_defaults_to_utterplan_and_writes_v6_plans(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Platform Decay - Martha Wells.ssmd-bundle"
    contents = {number: _ssmd(f"Chapter {number} content.") for number in range(1, 24)}
    _write_book(root, tuple(range(1, 24)), contents=contents)
    manifest_before = (root / "manifest.json").read_bytes()

    result = main(
        ["bundle", "compile", str(root), "--chapters", "5-17", "--text-preparation", "identity"]
    )

    captured = capsys.readouterr()
    output_dir = root / "utterplan"
    assert result == 0
    assert captured.out == ""
    assert "selected:  13" in captured.err
    assert "chapter-0005" in captured.err and "chapter-0017" in captured.err
    assert sorted(path.name for path in output_dir.glob("*.utterplan.toml")) == [
        f"chapter-{number:04d}.utterplan.toml" for number in range(5, 18)
    ]
    assert _plan_text(output_dir / "chapter-0005.utterplan.toml") == "Chapter 5 content."
    report = _report(output_dir / "compile-report.toml")
    assert report["requested"] == 13
    assert report["version"] == 2
    assert report["written"] == 13
    assert report["failed"] == 0
    assert [item["id"] for item in report["item"]] == [
        f"chapter-{number:04d}" for number in range(5, 18)
    ]
    first = report["item"][0]
    assert first["preparation_mode"] == "identity"
    assert first["repair_count"] == 0
    assert first["repairs"] == []
    assert first["degraded_linguistics"] is False
    assert (
        FlowPlan.load(output_dir / "chapter-0005.utterplan.toml").producer["text_preparation"]
        == "identity"
    )
    assert (root / "manifest.json").read_bytes() == manifest_before


def test_compile_book_report_records_ssmd_mode_and_repaired_cut_details(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repair.ssmd-bundle"
    _write_book(root, (5,), contents={5: _ssmd("lifecycle now")})

    def split_inside_token(text: str, **_kwargs: object) -> list[SimpleNamespace]:
        cut = 4
        return [
            SimpleNamespace(char_start=0, char_end=cut, text=text[:cut]),
            SimpleNamespace(char_start=cut, char_end=len(text), text=text[cut:]),
        ]

    monkeypatch.setitem(
        sys.modules, "phrasplit", SimpleNamespace(split_with_offsets=split_inside_token)
    )
    result = main(["bundle", "compile", str(root), "--chapters", "5", "--spacy", "off"])
    captured = capsys.readouterr()

    assert result == 0
    assert "preparation: ssmd; linguistics: full" in captured.err
    assert "segmentation.lexical_boundary_merged" not in captured.err
    item = _report(root / "utterplan/compile-report.toml")["item"][0]
    assert item["preparation_mode"] == "ssmd"
    assert item["repair_count"] >= 1
    assert any(
        diagnostic["code"] == "segmentation.lexical_boundary_merged"
        for diagnostic in item["diagnostics"]
    )
    assert any(
        repair["code"] == "segmentation.lexical_boundary_merged" for repair in item["repairs"]
    )
    assert item["degraded_linguistics"] is False
    assert _plan_text(root / "utterplan/chapter-0005.utterplan.toml") == "lifecycle now"


def test_compile_rejects_chapters_directory_as_non_root_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "book.ssmd-bundle"
    _write_book(root, (5,), contents={5: _ssmd("Chapter 5.")})

    result = main(["bundle", "compile", str(root / "chapters")])
    captured = capsys.readouterr()

    assert result == 2
    assert "canonical SSMD bundle root" in captured.err
    assert not (root / "utterplan").exists()


def test_compile_book_compiles_dirty_current_content_without_mutating_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "editable.ssmd-bundle"
    _write_book(root, (5,), contents={5: _ssmd("Original content.")})
    manifest = root / "manifest.json"
    manifest_before = manifest.read_bytes()
    source = root / "chapters/chapter-0005.ssmd.md"
    source.write_text(_ssmd("Edited workspace content."), encoding="utf-8")

    result = main(
        ["bundle", "compile", str(root), "--chapters", "5", "--text-preparation", "identity"]
    )

    capsys.readouterr()
    assert result == 0
    assert _plan_text(root / "utterplan/chapter-0005.utterplan.toml") == "Edited workspace content."
    assert manifest.read_bytes() == manifest_before


def test_unselected_missing_or_malformed_chapter_does_not_block_selected_range(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "subset.ssmd-bundle"
    _write_book(
        root,
        (5, 6, 20),
        contents={5: _ssmd("Five."), 6: _ssmd("Six."), 20: "not valid SSMD"},
    )
    (root / "chapters/chapter-0020.ssmd.md").unlink()

    result = main(
        ["bundle", "compile", str(root), "--chapters", "5-6", "--text-preparation", "identity"]
    )

    capsys.readouterr()
    assert result == 0
    assert (root / "utterplan/chapter-0005.utterplan.toml").exists()
    assert (root / "utterplan/chapter-0006.utterplan.toml").exists()
    assert not (root / "utterplan/chapter-0020.utterplan.toml").exists()


@pytest.mark.parametrize("selector", ["5-7", "17-5", "5,,7", "0"])
def test_selector_usage_errors_preflight_before_creating_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], selector: str
) -> None:
    root = tmp_path / "invalid-selection.ssmd-bundle"
    _write_book(root, (5, 7), contents={5: _ssmd("Five."), 7: _ssmd("Seven.")})
    output_dir = tmp_path / "outside-plans"

    result = main(
        ["bundle", "compile", str(root), "--chapters", selector, "--output-dir", str(output_dir)]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert not output_dir.exists()


def test_unrecognized_workspace_is_a_usage_error_without_output_writes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output_dir = tmp_path / "plans"

    result = main(
        ["bundle", "compile", str(tmp_path / "not-a-book"), "--output-dir", str(output_dir)]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "containing manifest.json" in captured.err
    assert not output_dir.exists()


def test_selected_invalid_ssmd_is_reported_and_later_chapters_continue(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "partial.ssmd-bundle"
    _write_book(
        root,
        (5, 6, 7),
        contents={5: _ssmd("Five."), 6: _ssmd("€"), 7: _ssmd("Seven.")},
    )

    result = main(
        ["bundle", "compile", str(root), "--chapters", "5-7", "--text-preparation", "identity"]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert (root / "utterplan/chapter-0005.utterplan.toml").exists()
    assert not (root / "utterplan/chapter-0006.utterplan.toml").exists()
    assert (root / "utterplan/chapter-0007.utterplan.toml").exists()
    report = _report(root / "utterplan/compile-report.toml")
    assert [item["status"] for item in report["item"]] == ["written", "failed", "written"]
    assert report["item"][1]["stage"] == "renderability"
    assert "[3/3] chapter-0007" in captured.err


def test_fail_fast_skips_remaining_book_chapters(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "fail-fast.ssmd-bundle"
    _write_book(
        root,
        (5, 6, 7),
        contents={5: _ssmd("Five."), 6: _ssmd("€"), 7: _ssmd("Seven.")},
    )

    result = main(
        [
            "bundle",
            "compile",
            str(root),
            "--chapters",
            "5-7",
            "--text-preparation",
            "identity",
            "--fail-fast",
        ]
    )

    capsys.readouterr()
    assert result == 1
    report = _report(root / "utterplan/compile-report.toml")
    assert [item["status"] for item in report["item"]] == ["written", "failed", "skipped"]
    assert not (root / "utterplan/chapter-0007.utterplan.toml").exists()


def test_existing_plan_is_protected_unless_force_is_used(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "force.ssmd-bundle"
    _write_book(root, (5,), contents={5: _ssmd("Replacement content.")})
    output = root / "utterplan/chapter-0005.utterplan.toml"
    output.parent.mkdir(parents=True)
    output.write_text("keep this", encoding="utf-8")
    args = [
        "bundle",
        "compile",
        str(root),
        "--language",
        "en-US",
        "--text-preparation",
        "identity",
    ]

    protected = main(args)
    capsys.readouterr()
    assert protected == 1
    assert output.read_text(encoding="utf-8") == "keep this"

    forced = main([*args, "--force"])
    capsys.readouterr()
    assert forced == 0
    assert _plan_text(output) == "Replacement content."


def test_missing_selected_source_is_a_reported_item_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "missing.ssmd-bundle"
    _write_book(root, (5,))

    result = main(["bundle", "compile", str(root), "--chapters", "5"])

    capsys.readouterr()
    assert result == 1
    report = _report(root / "utterplan/compile-report.toml")
    assert report["item"][0]["status"] == "failed"
    assert report["item"][0]["stage"] == "read"


def test_unsafe_path_and_symlink_escape_are_usage_errors_before_writes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "unsafe.ssmd-bundle"
    _write_book(root, (5,), paths={5: "chapters/../outside.ssmd.md"})
    result = main(["bundle", "compile", str(root)])
    first = capsys.readouterr()
    assert result == 2
    assert not (root / "utterplan").exists()
    assert "chapters" in first.err

    safe_root = tmp_path / "symlink.ssmd-bundle"
    _write_book(safe_root, (5,))
    outside = tmp_path / "outside.ssmd.md"
    outside.write_text(_ssmd("Outside."), encoding="utf-8")
    link = safe_root / "chapters/chapter-0005.ssmd.md"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    result = main(["bundle", "compile", str(safe_root)])
    second = capsys.readouterr()
    assert result == 2
    assert "escapes workspace" in second.err
    assert not (safe_root / "utterplan").exists()


def test_preflights_duplicate_output_and_report_source_collisions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "collisions.ssmd-bundle"
    _write_book(
        root,
        (1, 2),
        contents={1: _ssmd("One."), 2: _ssmd("Two.")},
        paths={1: "chapters/part-a/chapter.ssmd.md", 2: "chapters/part-b/chapter.ssmd.md"},
    )
    result = main(["bundle", "compile", str(root)])
    captured = capsys.readouterr()
    assert result == 2
    assert "map to the same output" in captured.err
    assert not (root / "utterplan").exists()

    root2 = tmp_path / "report-collision.ssmd-bundle"
    _write_book(root2, (5,), contents={5: _ssmd("Five.")})
    result = main(["bundle", "compile", str(root2), "--report", str(root2 / "manifest.json")])
    captured = capsys.readouterr()
    assert result == 2
    assert "source workspace content" in captured.err
    assert not (root2 / "utterplan").exists()
    assert (
        json.loads((root2 / "manifest.json").read_text(encoding="utf-8"))["format"]
        == "ssmdconvert.book"
    )


def test_output_and_report_cannot_be_written_into_chapters_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "readonly-source.ssmd-bundle"
    _write_book(root, (5,), contents={5: _ssmd("Five.")})
    result = main(
        [
            "bundle",
            "compile",
            str(root),
            "--output-dir",
            str(root / "chapters" / "plans"),
        ]
    )
    captured = capsys.readouterr()
    assert result == 2
    assert "must not be inside" in captured.err
    assert not (root / "chapters/plans").exists()


def test_compile_book_parser_exposes_shared_options_but_no_input_format() -> None:
    args = build_parser().parse_args(
        ["bundle", "compile", "book.ssmd-bundle", "--chapters", "1,3-5", "--language", "en-US"]
    )
    assert args.chapters == "1,3-5"
    assert args.language == "en-US"
    assert args.output_dir is None
    assert args.spacy == "auto"
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["bundle", "compile", "book.ssmd-bundle", "--input-format", "ssmd"]
        )


def test_default_all_selection_and_explicit_output_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "all-chapters.ssmd-bundle"
    _write_book(
        root,
        (1, 3, 4, 5, 9),
        contents={number: _ssmd(f"Chapter {number}.") for number in (1, 3, 4, 5, 9)},
    )
    output_dir = tmp_path / "build" / "plans"

    result = main(
        [
            "bundle",
            "compile",
            str(root),
            "--output-dir",
            str(output_dir),
            "--text-preparation",
            "identity",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "chapters:  all" in captured.err
    assert len(list(output_dir.glob("*.utterplan.toml"))) == 5
    assert _report(output_dir / "compile-report.toml")["requested"] == 5
    assert not (root / "utterplan").exists()


def test_report_path_collision_with_plan_output_is_preflighted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "report-plan-collision.ssmd-bundle"
    _write_book(root, (5,), contents={5: _ssmd("Five.")})
    output_dir = tmp_path / "plans"

    result = main(
        [
            "bundle",
            "compile",
            str(root),
            "--output-dir",
            str(output_dir),
            "--report",
            str(output_dir / "chapter-0005.utterplan.toml"),
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "report path collides with plan output" in captured.err
    assert not output_dir.exists()


def test_compile_book_localizes_fallback_boundaries_with_default_settings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "fallback-boundaries.ssmd-bundle"
    _write_book(
        root,
        (5, 6),
        contents={
            5: _ssmd('[alpha]{emphasis="strong"}—beta'),
            6: _ssmd('alpha—[beta]{emphasis="strong"}'),
        },
    )

    result = main(["bundle", "compile", str(root), "--chapters", "5-6", "--spacy", "off"])
    capsys.readouterr()

    assert result == 0
    output_dir = root / "utterplan"
    report = _report(output_dir / "compile-report.toml")
    assert report["requested"] == 2
    assert report["written"] == 2
    assert report["failed"] == 0
    assert report["skipped"] == 0
    assert report["complete"] is True

    for number, expected_surface in ((5, "alpha"), (6, "beta")):
        plan_path = output_dir / f"chapter-{number:04d}.utterplan.toml"
        assert plan_path.exists()
        plan = FlowPlan.load(plan_path)
        assert plan.linguistics[0].provider == "fallback"
        surfaces = {
            segment.text[token.start : token.end]
            for unit in plan.flow
            for segment in unit.segments
            for token in segment.tokens
        }
        assert expected_surface in surfaces
