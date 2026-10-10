from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from utterplan import FlowPlan, PlannerConfig, compile_attempt
from utterplan.cli import build_parser, main
from utterplan.migration import migrate_plan_data


def _payload(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    captured = capsys.readouterr()
    assert captured.err == ""
    return FlowPlan.from_toml(captured.out).to_dict()


def _first_segment(payload: dict[str, object]) -> dict[str, object]:
    flow = payload["flow"]
    assert isinstance(flow, list) and flow
    segments = flow[0]["segments"]
    assert isinstance(segments, list) and segments and isinstance(segments[0], dict)
    return segments[0]


def _segment_text(payload: dict[str, object]) -> str:
    return str(_first_segment(payload)["text"])


def _write_legacy_json(path: Path) -> dict[str, object]:
    fixture = Path(__file__).parent / "migration/fixtures/v4/basic_en.utterplan.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def test_compile_cli_defaults() -> None:
    args = build_parser().parse_args(["compile", "Hello world.", "--lang", "en"])

    assert args.text_preparation == "spokenform"
    assert args.pause_mode == "tts"
    assert args.spacy == "off"

    assert args.renderability == "repair"


def test_compile_literal_text_to_stdout_toml(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["compile", "Hello world.", "--lang", "en-us"]) == 0
    payload = _payload(capsys)
    assert payload["format"] == "utterplan"
    assert payload["schema_version"] == 5
    assert payload["flow"]


def test_compile_multi_token_literal_text(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["compile", "Hello", "world.", "--lang", "en-us"]) == 0
    payload = _payload(capsys)
    assert _segment_text(payload) == "Hello world."


def test_compile_reads_stdin_when_text_is_omitted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("Hello from stdin."))
    assert main(["compile", "--lang", "en-us"]) == 0
    assert _segment_text(_payload(capsys)) == "Hello from stdin."


def test_compile_positional_existing_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("Hello from a file.", encoding="utf-8")
    assert main(["compile", str(source), "--lang", "en-us"]) == 0
    payload = _payload(capsys)
    assert _segment_text(payload) == "Hello from a file."
    assert payload["document"]["format"] == "plain"


def test_compile_explicit_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "source.txt"
    source.write_text("Explicit file input.", encoding="utf-8")
    assert main(["compile", "--file", str(source), "--lang", "en-us"]) == 0
    assert _segment_text(_payload(capsys)) == "Explicit file input."


def test_compile_explicit_text_disables_file_detection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "literal.txt"
    source.write_text("file contents", encoding="utf-8")
    assert main(["compile", str(source), "--input-format", "text", "--lang", "en-us"]) == 0
    assert "file contents" not in _segment_text(_payload(capsys))


def test_compile_auto_detects_ssmd_suffix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "chapter.ssmd"
    source.write_text("Hello SSMD.", encoding="utf-8")
    assert main(["compile", str(source), "--lang", "en-us"]) == 0
    assert _payload(capsys)["document"]["format"] == "ssmd"


def test_compile_explicit_ssmd_from_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("Hello SSMD."))
    assert main(["compile", "--lang", "en-us", "--input-format", "ssmd"]) == 0
    assert _payload(capsys)["document"]["format"] == "ssmd"


def test_compile_output_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "plan.utterplan.toml"
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(output)]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "wrote" in captured.err
    assert FlowPlan.load(output).to_dict()["format"] == "utterplan"


def test_compile_output_file_and_toml_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "plan.utterplan.toml"
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(output), "--stdout"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert FlowPlan.from_toml(captured.out).to_dict() == FlowPlan.load(output).to_dict()


def test_compile_refuses_existing_output_without_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "plan.utterplan.toml"
    output.write_text("sentinel", encoding="utf-8")
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(output)]) == 1
    captured = capsys.readouterr()
    assert "--force" in captured.err
    assert output.read_text(encoding="utf-8") == "sentinel"


def test_compile_force_replaces_existing_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "plan.utterplan.toml"
    output.write_text("sentinel", encoding="utf-8")
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(output), "--force"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "wrote" in captured.err
    assert FlowPlan.load(output).to_dict()["format"] == "utterplan"


def test_compile_toml_stdout_contains_no_status_text(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["compile", "Hello.", "--lang", "en-us", "--stdout"]) == 0
    captured = capsys.readouterr()
    assert "wrote" not in captured.out
    FlowPlan.from_toml(captured.out).to_dict()


def test_compile_status_goes_to_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "plan.utterplan.toml"
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(output)]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("wrote ")


def test_compile_invalid_ssmd_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "broken.ssmd"
    source.write_text(
        """---
ssmd_version: "0.9"
pause_defaults: [
---
Hello.""",
        encoding="utf-8",
    )
    assert main(["compile", str(source), "--lang", "en-us"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Traceback" not in captured.err


def test_compile_strict_renderability_reports_source_and_writes_no_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "broken.txt"
    output = tmp_path / "plan.utterplan.toml"
    source.write_text("Hello.\n\n.\n\nWorld.", encoding="utf-8")

    result = main(
        [
            "compile",
            "--file",
            str(source),
            "--lang",
            "en-us",
            "--text-preparation",
            "identity",
            "--renderability",
            "strict",
            "-o",
            str(output),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert not output.exists()
    assert captured.out == ""
    assert f"{source}:3:1" in captured.err
    assert "isolated punctuation became its own speech segment" in captured.err
    assert "Prepared fragment:" in captured.err and "Spoken context:" in captured.err
    assert "Automatic repair: safe;" in captured.err


def test_compile_repair_cli_blocks_unattachable_punctuation_without_loss(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "repair.txt"
    output = tmp_path / "plan.utterplan.toml"
    source.write_text("Hello.\n\n.\n\nWorld.", encoding="utf-8")

    result = main(
        [
            "compile",
            "--file",
            str(source),
            "--lang",
            "en-us",
            "--text-preparation",
            "identity",
            "--renderability",
            "repair",
            "-o",
            str(output),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert not output.exists()
    assert "isolated punctuation became its own speech segment" in captured.err
    assert "Prepared fragment: '.'" in captured.err
    assert "Automatic repair: safe; remove the isolated punctuation-only segment." in captured.err


def test_top_level_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as result:
        main(["--version"])
    assert result.value.code == 0
    assert capsys.readouterr().out.startswith("utterplan ")


def test_validate_valid_plan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "plan.utterplan.toml"
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(output)]) == 0
    capsys.readouterr()
    assert main(["validate", str(output)]) == 0
    assert "valid" in capsys.readouterr().out


def test_validate_rejects_legacy_json_plan_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    invalid = tmp_path / "legacy.utterplan.json"
    invalid.write_text("{}", encoding="utf-8")
    assert main(["validate", str(invalid)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "format.unsupported_json" in captured.err


def test_inspect_segment(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "plan.utterplan.toml"
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(output)]) == 0
    capsys.readouterr()
    assert main(["inspect", str(output), "--segment", "0"]) == 0
    captured = capsys.readouterr()
    assert "Segment 0" in captured.out
    assert "Hello" in captured.out


def test_inspect_tokens_shows_linguistic_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "plan.utterplan.toml"
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(output)]) == 0
    capsys.readouterr()
    assert main(["inspect", str(output), "--tokens"]) == 0
    captured = capsys.readouterr()
    assert "Linguistic provenance: 1" in captured.out
    assert "lemma=hello." in captured.out
    assert "pos=-" in captured.out
    assert "tag=-" in captured.out
    assert "morph=-" in captured.out


def test_inspect_preparation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "plan.utterplan.toml"
    trace = tmp_path / "compiler.trace.toml"
    assert (
        main(
            [
                "compile",
                "Dr. bought 5 kg.",
                "--lang",
                "en-us",
                "-o",
                str(output),
                "--trace",
                str(trace),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["inspect-trace", str(trace), "--preparation"]) == 0
    captured = capsys.readouterr()
    assert "Preparation" in captured.out
    assert "backend: spokenform" in captured.out
    assert "replacements: 2" in captured.out
    assert "Dr." in captured.out
    assert "Doctor" in captured.out


def test_inspect_semantic_boundaries_are_separate_from_boundary_events(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    trace = tmp_path / "compiler.trace.toml"
    assert main(["compile", "One. Two.", "--lang", "en-us", "--trace", str(trace)]) == 0
    capsys.readouterr()

    assert main(["inspect-trace", str(trace), "--boundaries"]) == 0
    inspected = capsys.readouterr().out
    assert "Boundary events" in inspected
    assert "Semantic boundary candidates" in inspected
    assert "semantic-boundary-000000" in inspected
    assert "sentence" in inspected


def test_compile_file_and_positional_text_are_mutually_exclusive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("Hello.", encoding="utf-8")
    assert main(["compile", "extra", "--file", str(source), "--lang", "en-us"]) == 1
    assert "cannot be combined" in capsys.readouterr().err


def test_explain_plan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "plan.utterplan.toml"
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(output)]) == 0
    capsys.readouterr()

    assert main(["explain", str(output)]) == 0
    captured = capsys.readouterr()
    assert "UtterPlan explanation" in captured.out
    assert "Speech plan" in captured.out
    assert '[en-us] "Hello."' in captured.out
    assert captured.err == ""


def test_explain_details(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "plan.utterplan.toml"
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(output)]) == 0
    capsys.readouterr()

    assert main(["explain", str(output), "--details"]) == 0
    captured = capsys.readouterr()
    assert "plan id: sha256:" in captured.out
    assert "local tokens:" in captured.out
    assert captured.err == ""


def test_explain_rejects_legacy_json_plan_files_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    invalid = tmp_path / "legacy.utterplan.json"
    invalid.write_text("{}", encoding="utf-8")

    assert main(["explain", str(invalid)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "format.unsupported_json" in captured.err
    assert "Traceback" not in captured.err


def test_migrate_explicitly_checks_legacy_json_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "legacy.utterplan.json"
    _write_legacy_json(source)
    assert main(["migrate", str(source), "--check"]) == 0
    captured = capsys.readouterr()
    assert "valid migration path" in captured.out
    assert "source schema: 4" in captured.out
    assert "migration required: yes" in captured.out
    assert source.exists()


def test_migrate_imports_json_to_toml_stdout_and_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "legacy.utterplan.json"
    original = FlowPlan.from_dict(migrate_plan_data(_write_legacy_json(source)).data)
    destination = tmp_path / "copy.utterplan.toml"

    assert main(["migrate", str(source)]) == 0
    stdout_plan = FlowPlan.from_toml(capsys.readouterr().out)
    assert stdout_plan.to_dict() == original.to_dict()
    assert main(["migrate", str(source), "-o", str(destination)]) == 0
    assert "imported" in capsys.readouterr().err
    assert FlowPlan.load(destination).to_dict() == original.to_dict()


def test_migrate_refuses_existing_toml_output_without_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "legacy.utterplan.json"
    _write_legacy_json(source)
    destination = tmp_path / "copy.utterplan.toml"
    destination.write_text("sentinel", encoding="utf-8")
    assert main(["migrate", str(source), "-o", str(destination)]) == 1
    assert "--force" in capsys.readouterr().err
    assert destination.read_text(encoding="utf-8") == "sentinel"


def test_validate_reports_current_schema_for_toml_plans(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "current.utterplan.toml"
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(source)]) == 0
    capsys.readouterr()
    assert main(["validate", str(source)]) == 0
    captured = capsys.readouterr()
    assert "schema version: 5" in captured.out
    assert "plan ID: sha256:" in captured.out
    assert "migration required" not in captured.out


def test_compile_ssmd_header_language_without_cli_language(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "chapter.ssmd.md"
    source.write_text('---\nssmd_version: "0.9"\nlanguage: de-DE\n---\nHallo.', encoding="utf-8")

    assert main(["compile", str(source)]) == 0
    payload = _payload(capsys)
    assert _first_segment(payload)["language"] == "de-DE"


def test_compile_ssmd_cli_language_is_fallback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "chapter.ssmd"
    source.write_text("Hallo.", encoding="utf-8")

    assert main(["compile", str(source), "--language", "de-DE"]) == 0
    payload = _payload(capsys)
    assert _first_segment(payload)["language"] == "de-DE"


def test_compile_requires_language_for_plain_input(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["compile", "Hello."]) == 1
    captured = capsys.readouterr()
    assert "plain input requires --language" in captured.err


def test_compile_plain_input_with_required_language(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["compile", "Hallo.", "--input-format", "plain", "--language", "de-DE"]) == 0
    assert _first_segment(_payload(capsys))["language"] == "de-de"


def test_validate_source_documents_and_preserve_saved_plan_validation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ssmd = tmp_path / "chapter.ssmd.md"
    ssmd.write_text('---\nssmd_version: "0.9"\nlanguage: de-DE\n---\nHallo.', encoding="utf-8")
    assert main(["validate", str(ssmd)]) == 0
    assert "input format: ssmd" in capsys.readouterr().out

    plain = tmp_path / "plain.txt"
    plain.write_text("Hello.", encoding="utf-8")
    assert main(["validate", str(plain)]) == 1
    assert "plain input requires --language" in capsys.readouterr().err
    assert main(["validate", str(plain), "--input-format", "plain", "--language", "en-us"]) == 0
    assert "valid" in capsys.readouterr().out


def _save_blocked_attempt(tmp_path: Path):
    config = PlannerConfig(
        language="en-us",
        document_format="plain",
        text_preparation="identity",
        renderability_mode="strict",
    )
    attempt = compile_attempt("Hello.\n\n.\n\nWorld.", input_format="plain", config=config)
    path = tmp_path / "blocked.attempt.toml"
    attempt.save(path)
    return attempt, path


def test_inspect_attempt_reports_issues_segment_and_unit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    attempt, path = _save_blocked_attempt(tmp_path)
    issue_segment = attempt.renderability.issues[0].segment_id
    unit = attempt.candidate.units[0]

    assert (
        main(
            [
                "inspect-attempt",
                str(path),
                "--issues",
                "--segment",
                issue_segment,
                "--unit",
                unit.id,
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "status:        blocked" in output
    assert "renderability: blocked (strict)" in output
    assert "renderability.punctuation_only" in output
    assert "safe: true" in output
    assert f"Segment {issue_segment}" in output
    assert f"Unit {unit.id}" in output


def test_inspect_attempt_json_exposes_separate_artifact_schema(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    attempt, path = _save_blocked_attempt(tmp_path)

    assert main(["inspect-attempt", str(path), "--json"]) == 0
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["schema"] == "utterplan.planning-attempt.v1"
    assert payload["attempt"]["status"] == "blocked"
    assert payload["candidate"]["segments"]
    assert payload["renderability"]["issues"]
    assert payload["attempt"]["attempt_id"] == attempt.attempt_id
