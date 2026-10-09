"""Read-only discovery and selection for editable SSMDBook v1 workspaces."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

_MAX_MANIFEST_BYTES = 2 * 1024 * 1024


class SSMDBookError(ValueError):
    """An SSMDBook workspace or chapter selection is invalid."""


@dataclass(frozen=True, slots=True)
class SSMDBookChapter:
    id: str
    source_number: int
    title: str
    relative_path: str
    expected_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class SSMDBookIndex:
    root: Path
    manifest_path: Path
    chapters: tuple[SSMDBookChapter, ...]


def resolve_ssmdbook_root(path: str | Path) -> Path:
    """Resolve a book root or its canonical ``chapters/`` directory."""
    input_path = Path(path).expanduser()
    try:
        if input_path.is_dir() and (input_path / "manifest.json").is_file():
            return input_path.resolve(strict=True)
        if (
            input_path.name == "chapters"
            and input_path.is_dir()
            and (input_path.parent / "manifest.json").is_file()
        ):
            return input_path.parent.resolve(strict=True)
    except OSError as exc:
        raise SSMDBookError(f"cannot inspect ssmdbook input {input_path}: {exc}") from exc

    raise SSMDBookError(
        f"not an ssmdbook workspace: {path}\n"
        "expected manifest.json in the input directory or its parent"
    )


def load_ssmdbook_index(path: str | Path) -> SSMDBookIndex:
    """Read and validate the public SSMDBook v1 manifest without loading chapters."""
    root = resolve_ssmdbook_root(path)
    manifest_path = root / "manifest.json"
    try:
        if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
            raise SSMDBookError("ssmdbook manifest.json exceeds the 2 MiB size limit")
        with manifest_path.open("rb") as stream:
            raw = stream.read(_MAX_MANIFEST_BYTES + 1)
    except SSMDBookError:
        raise
    except OSError as exc:
        raise SSMDBookError(f"cannot read ssmdbook manifest {manifest_path}: {exc}") from exc

    if len(raw) > _MAX_MANIFEST_BYTES:
        raise SSMDBookError("ssmdbook manifest.json exceeds the 2 MiB size limit")
    try:
        text = raw.decode("utf-8")
        data = json.loads(text, parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise SSMDBookError(f"invalid ssmdbook manifest.json: {exc}") from exc
    if not isinstance(data, dict):
        raise SSMDBookError("ssmdbook manifest root must be a JSON object")
    if data.get("format") != "ssmdconvert.book":
        raise SSMDBookError("unsupported ssmdbook format; expected 'ssmdconvert.book'")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise SSMDBookError("unsupported ssmdbook schema_version; expected 1")
    if data.get("ssmd_version") != "0.9":
        raise SSMDBookError("unsupported ssmdbook ssmd_version; expected '0.9'")

    entries = data.get("chapters")
    if not isinstance(entries, list):
        raise SSMDBookError("ssmdbook manifest chapters must be an array")

    chapters: list[SSMDBookChapter] = []
    seen_ids: set[str] = set()
    seen_numbers: set[int] = set()
    seen_paths: set[str] = set()
    for index, entry in enumerate(entries):
        label = f"chapters[{index}]"
        if not isinstance(entry, dict):
            raise SSMDBookError(f"{label} must be an object")
        chapter_id = entry.get("id")
        source_number = entry.get("source_number")
        relative_path = entry.get("path")
        title = entry.get("title")
        digest = entry.get("sha256")

        if not isinstance(chapter_id, str) or not chapter_id.strip():
            raise SSMDBookError(f"{label}.id must be a non-empty string")
        if type(source_number) is not int or source_number <= 0:
            raise SSMDBookError(f"{label}.source_number must be a positive integer")
        if not isinstance(relative_path, str) or not relative_path:
            raise SSMDBookError(f"{label}.path must be a non-empty normalized relative POSIX path")
        _validate_relative_chapter_path(relative_path, label=f"{label}.path")
        if not isinstance(title, str):
            raise SSMDBookError(f"{label}.title must be a string")
        if digest is not None and not isinstance(digest, str):
            raise SSMDBookError(f"{label}.sha256 must be a string when present")
        if chapter_id in seen_ids:
            raise SSMDBookError(f"duplicate ssmdbook chapter id: {chapter_id}")
        if source_number in seen_numbers:
            raise SSMDBookError(f"duplicate ssmdbook source_number: {source_number}")
        if relative_path in seen_paths:
            raise SSMDBookError(f"duplicate ssmdbook chapter path: {relative_path}")

        seen_ids.add(chapter_id)
        seen_numbers.add(source_number)
        seen_paths.add(relative_path)
        chapters.append(
            SSMDBookChapter(
                id=chapter_id,
                source_number=source_number,
                title=title,
                relative_path=relative_path,
                expected_sha256=digest,
            )
        )

    return SSMDBookIndex(root=root, manifest_path=manifest_path, chapters=tuple(chapters))


def select_ssmdbook_chapters(
    book: SSMDBookIndex,
    selector: str | None,
) -> tuple[SSMDBookChapter, ...]:
    """Select by source chapter number while preserving manifest order."""
    if selector is None:
        selector = "all"
    selector = selector.strip()
    if not selector:
        raise SSMDBookError("chapter selector must not be empty")
    if selector == "all":
        return book.chapters

    intervals: list[tuple[int, int]] = []
    for token in selector.split(","):
        token = token.strip()
        if not token:
            raise SSMDBookError(f"malformed chapter selector: {selector!r}")
        if "-" in token:
            if token.count("-") != 1:
                raise SSMDBookError(f"malformed chapter range: {token!r}")
            first_text, last_text = (part.strip() for part in token.split("-", 1))
            first = _parse_positive_number(first_text, selector)
            last = _parse_positive_number(last_text, selector)
            if first > last:
                raise SSMDBookError(f"reversed chapter range: {token!r}")
            intervals.append((first, last))
        else:
            number = _parse_positive_number(token, selector)
            intervals.append((number, number))

    merged: list[tuple[int, int]] = []
    for first, last in sorted(intervals):
        if merged and first <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], last))
        else:
            merged.append((first, last))

    available_numbers = sorted(chapter.source_number for chapter in book.chapters)
    selected_numbers: set[int] = set()
    for first, last in merged:
        next_expected = first
        for number in available_numbers:
            if number < first:
                continue
            if number > last:
                break
            if number > next_expected:
                raise SSMDBookError(
                    f"chapter selector references missing source number(s): {next_expected}"
                )
            selected_numbers.add(number)
            next_expected = number + 1
        if next_expected <= last:
            raise SSMDBookError(
                f"chapter selector references missing source number(s): {next_expected}"
            )
    return tuple(chapter for chapter in book.chapters if chapter.source_number in selected_numbers)


def selected_chapter_path(book: SSMDBookIndex, chapter: SSMDBookChapter) -> Path:
    """Return a selected chapter path after checking containment and symlinks."""
    _validate_relative_chapter_path(chapter.relative_path, label=f"chapter {chapter.id!r} path")
    source = book.root.joinpath(*PurePosixPath(chapter.relative_path).parts)
    try:
        resolved = source.resolve(strict=False)
        resolved.relative_to(book.root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SSMDBookError(
            f"ssmdbook chapter path escapes workspace root: {chapter.relative_path}"
        ) from exc

    # Missing files remain per-item read failures in the existing batch compiler.
    # Existing targets must be regular files; resolve() also detects symlink escapes.
    try:
        exists_or_link = source.exists() or source.is_symlink()
        if exists_or_link and not resolved.is_file():
            raise SSMDBookError(f"ssmdbook chapter is not a regular file: {chapter.relative_path}")
    except OSError as exc:
        raise SSMDBookError(
            f"cannot inspect ssmdbook chapter {chapter.relative_path}: {exc}"
        ) from exc
    return source


def _parse_positive_number(value: str, selector: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise SSMDBookError(f"malformed chapter selector: {selector!r}")
    try:
        number = int(value)
    except ValueError as exc:
        raise SSMDBookError(f"malformed chapter selector: {selector!r}") from exc
    if number <= 0:
        raise SSMDBookError("chapter numbers in selector must be positive integers")
    return number


def _validate_relative_chapter_path(value: str, *, label: str) -> None:
    if "\x00" in value:
        raise SSMDBookError(f"{label} must not contain NUL")
    if "\\" in value:
        raise SSMDBookError(f"{label} must use normalized POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or PureWindowsPath(value).drive:
        raise SSMDBookError(f"{label} must be a relative POSIX path")
    if any(part in {".", ".."} for part in path.parts):
        raise SSMDBookError(f"{label} must not contain '.' or '..' path components")
    if path.as_posix() != value or not value.startswith("chapters/") or len(path.parts) < 2:
        raise SSMDBookError(f"{label} must be a normalized path below 'chapters/'")


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-standard JSON constant {value!r}")


__all__ = [
    "SSMDBookChapter",
    "SSMDBookError",
    "SSMDBookIndex",
    "load_ssmdbook_index",
    "resolve_ssmdbook_root",
    "selected_chapter_path",
    "select_ssmdbook_chapters",
]
