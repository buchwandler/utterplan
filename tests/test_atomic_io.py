from __future__ import annotations

from pathlib import Path

import pytest

from utterplan.atomic_io import atomic_write_text


def test_atomic_write_replaces_target_with_utf8_text(tmp_path: Path) -> None:
    target = tmp_path / "plan.toml"
    target.write_text("old", encoding="utf-8")

    atomic_write_text(target, "new café\n")

    assert target.read_text(encoding="utf-8") == "new café\n"
    assert list(tmp_path.iterdir()) == [target]


def test_failed_replace_preserves_existing_file_and_removes_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "plan.toml"
    target.write_text("previous", encoding="utf-8")

    def fail_replace(source: object, destination: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("utterplan.atomic_io.os.replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        atomic_write_text(target, "replacement")

    assert target.read_text(encoding="utf-8") == "previous"
    assert list(tmp_path.iterdir()) == [target]


def test_parent_creation_is_explicit(tmp_path: Path) -> None:
    target = tmp_path / "not-created" / "plan.toml"
    with pytest.raises(FileNotFoundError):
        atomic_write_text(target, "no parent")
    assert not target.parent.exists()

    atomic_write_text(target, "created", create_parent=True)
    assert target.read_text(encoding="utf-8") == "created"
