from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from utterplan.cli import build_parser, main


def _payload(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def test_compile_cli_defaults() -> None:
    args = build_parser().parse_args(["compile", "Hello world.", "--lang", "en"])

    assert args.text_preparation == "spokenform"
    assert args.pause_mode == "tts"
    assert args.spacy == "off"


def test_compile_literal_text_to_stdout_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["compile", "Hello world.", "--lang", "en-us"]) == 0
    payload = _payload(capsys)
    assert payload["format"] == "utterplan"
    assert payload["schema_version"] == 2
    assert payload["segments"]


def test_compile_multi_token_literal_text(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["compile", "Hello", "world.", "--lang", "en-us"]) == 0
    payload = _payload(capsys)
    assert payload["source"]["text"] == "Hello world."


def test_compile_reads_stdin_when_text_is_omitted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("Hello from stdin."))
    assert main(["compile", "--lang", "en-us"]) == 0
    assert _payload(capsys)["source"]["text"] == "Hello from stdin."


def test_compile_positional_existing_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("Hello from a file.", encoding="utf-8")
    assert main(["compile", str(source), "--lang", "en-us"]) == 0
    payload = _payload(capsys)
    assert payload["source"]["text"] == "Hello from a file."
    assert payload["source"]["format"] == "plain"


def test_compile_explicit_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "source.txt"
    source.write_text("Explicit file input.", encoding="utf-8")
    assert main(["compile", "--file", str(source), "--lang", "en-us"]) == 0
    assert _payload(capsys)["source"]["text"] == "Explicit file input."


def test_compile_explicit_text_disables_file_detection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "literal.txt"
    source.write_text("file contents", encoding="utf-8")
    assert main(["compile", str(source), "--input-format", "text", "--lang", "en-us"]) == 0
    assert _payload(capsys)["source"]["text"] == str(source)


def test_compile_auto_detects_ssmd_suffix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "chapter.ssmd"
    source.write_text("Hello SSMD.", encoding="utf-8")
    assert main(["compile", str(source), "--lang", "en-us"]) == 0
    assert _payload(capsys)["source"]["format"] == "ssmd"


def test_compile_explicit_ssmd_from_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("Hello SSMD."))
    assert main(["compile", "--lang", "en-us", "--input-format", "ssmd"]) == 0
    assert _payload(capsys)["source"]["format"] == "ssmd"


def test_compile_output_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "plan.utterplan.json"
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(output)]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "wrote" in captured.err
    assert json.loads(output.read_text(encoding="utf-8"))["format"] == "utterplan"


def test_compile_output_file_and_json_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "plan.utterplan.json"
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(output), "--json"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == json.loads(output.read_text(encoding="utf-8"))


def test_compile_refuses_existing_output_without_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "plan.utterplan.json"
    output.write_text("sentinel", encoding="utf-8")
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(output)]) == 1
    captured = capsys.readouterr()
    assert "--force" in captured.err
    assert output.read_text(encoding="utf-8") == "sentinel"


def test_compile_force_replaces_existing_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "plan.utterplan.json"
    output.write_text("sentinel", encoding="utf-8")
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(output), "--force"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "wrote" in captured.err
    assert json.loads(output.read_text(encoding="utf-8"))["format"] == "utterplan"


def test_compile_json_stdout_contains_no_status_text(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["compile", "Hello.", "--lang", "en-us", "--json"]) == 0
    captured = capsys.readouterr()
    assert "wrote" not in captured.out
    json.loads(captured.out)


def test_compile_status_goes_to_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "plan.utterplan.json"
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(output)]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("wrote ")


def test_compile_invalid_ssmd_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "broken.ssmd"
    source.write_text("---\npause_defaults: [\n---\nHello.", encoding="utf-8")
    assert main(["compile", str(source), "--lang", "en-us"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Traceback" not in captured.err


def test_top_level_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as result:
        main(["--version"])
    assert result.value.code == 0
    assert capsys.readouterr().out.startswith("utterplan ")


def test_validate_valid_plan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "plan.utterplan.json"
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(output)]) == 0
    capsys.readouterr()
    assert main(["validate", str(output)]) == 0
    assert "valid" in capsys.readouterr().out


def test_validate_invalid_plan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    assert main(["validate", str(invalid)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "format.invalid" in captured.err


def test_inspect_segment(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "plan.utterplan.json"
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(output)]) == 0
    capsys.readouterr()
    assert main(["inspect", str(output), "--segment", "0"]) == 0
    captured = capsys.readouterr()
    assert "Segment 0" in captured.out
    assert "Hello" in captured.out


def test_inspect_tokens_shows_linguistic_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "plan.utterplan.json"
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(output)]) == 0
    capsys.readouterr()
    assert main(["inspect", str(output), "--tokens"]) == 0
    captured = capsys.readouterr()
    assert "provider: fallback" in captured.out
    assert "lemma=hello." in captured.out
    assert "pos=-" in captured.out
    assert "tag=-" in captured.out
    assert "morph=-" in captured.out


def test_inspect_preparation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "plan.utterplan.json"
    assert main(["compile", "Dr. bought 5 kg.", "--lang", "en-us", "-o", str(output)]) == 0
    capsys.readouterr()
    assert main(["inspect", str(output), "--preparation"]) == 0
    captured = capsys.readouterr()
    assert "Preparation" in captured.out
    assert "backend: spokenform" in captured.out
    assert "replacements: 2" in captured.out
    assert "Dr." in captured.out
    assert "Doctor" in captured.out


def test_compile_file_and_positional_text_are_mutually_exclusive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("Hello.", encoding="utf-8")
    assert main(["compile", "extra", "--file", str(source), "--lang", "en-us"]) == 1
    assert "cannot be combined" in capsys.readouterr().err


def test_explain_plan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "plan.utterplan.json"
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(output)]) == 0
    capsys.readouterr()

    assert main(["explain", str(output)]) == 0
    captured = capsys.readouterr()
    assert "UtterPlan explanation" in captured.out
    assert "Speech plan" in captured.out
    assert '[en-us] "Hello."' in captured.out
    assert captured.err == ""


def test_explain_details(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "plan.utterplan.json"
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(output)]) == 0
    capsys.readouterr()

    assert main(["explain", str(output), "--details"]) == 0
    captured = capsys.readouterr()
    assert "plan id: sha256:" in captured.out
    assert "spoken: 0:6" in captured.out
    assert captured.err == ""


def test_explain_invalid_plan_returns_one_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")

    assert main(["explain", str(invalid)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "format.invalid" in captured.err
    assert "Traceback" not in captured.err


def test_migrate_check_current_plan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "current.json"
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(source)]) == 0
    capsys.readouterr()
    assert main(["migrate", str(source), "--check"]) == 0
    captured = capsys.readouterr()
    assert "valid migration path" in captured.out
    assert "source schema: 2" in captured.out
    assert "migration required: no" in captured.out
    assert source.exists()


def test_migrate_stdout_and_output_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "current.json"
    destination = tmp_path / "copy.json"
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(source)]) == 0
    capsys.readouterr()
    assert main(["migrate", str(source)]) == 0
    assert json.loads(capsys.readouterr().out)["schema_version"] == 2
    assert main(["migrate", str(source), "-o", str(destination)]) == 0
    assert "migrated" in capsys.readouterr().err
    assert json.loads(destination.read_text(encoding="utf-8"))["format"] == "utterplan"


def test_migrate_refuses_existing_output_without_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "current.json"
    destination = tmp_path / "copy.json"
    destination.write_text("sentinel", encoding="utf-8")
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(source)]) == 0
    capsys.readouterr()
    assert main(["migrate", str(source), "-o", str(destination)]) == 1
    assert "--force" in capsys.readouterr().err
    assert destination.read_text(encoding="utf-8") == "sentinel"


def test_validate_reports_migration_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "current.json"
    assert main(["compile", "Hello.", "--lang", "en-us", "-o", str(source)]) == 0
    capsys.readouterr()
    assert main(["validate", str(source)]) == 0
    captured = capsys.readouterr()
    assert "source schema version: 2" in captured.out
    assert "current schema version: 2" in captured.out
    assert "migration required: no" in captured.out
