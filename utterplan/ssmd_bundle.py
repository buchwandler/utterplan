"""Read-only loading and safe path resolution for canonical SSMD bundles."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal

BundleKind = Literal["book", "document"]

_BOOK_FORMAT = "ssmdconvert.book"
_DOCUMENT_FORMAT = "ssmdconvert.document"
_SCHEMA_VERSION = 1
_SSMD_VERSION = "0.9"
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_DOCUMENT_BYTES = 64 * 1024 * 1024
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class SsmdBundleError(ValueError):
    """A bundle root, manifest, or item path is invalid or unsafe."""


@dataclass(frozen=True, slots=True)
class BundleItem:
    id: str
    relative_path: str
    source_number: int
    title: str | None
    expected_sha256: str | None


@dataclass(frozen=True, slots=True)
class SsmdBundleIndex:
    root: Path
    manifest_path: Path
    kind: BundleKind
    items: tuple[BundleItem, ...]


def load_ssmd_bundle(path: str | Path) -> SsmdBundleIndex:
    """Load and validate a canonical bundle directory and its manifest."""
    root = resolve_ssmd_bundle_root(path)
    manifest_path = root / "manifest.json"
    data = _read_manifest(manifest_path, root)

    bundle_format = data.get("format")
    if bundle_format == _BOOK_FORMAT:
        kind: BundleKind = "book"
        _validate_header(data, expected_format=_BOOK_FORMAT)
        items = _book_items(data)
    elif bundle_format == _DOCUMENT_FORMAT:
        kind = "document"
        _validate_header(data, expected_format=_DOCUMENT_FORMAT)
        items = _document_items(data)
    else:
        raise SsmdBundleError(
            f"unsupported bundle format {bundle_format!r}; expected "
            f"{_BOOK_FORMAT!r} or {_DOCUMENT_FORMAT!r}"
        )

    return SsmdBundleIndex(root=root, manifest_path=manifest_path, kind=kind, items=items)


def select_bundle_items(index: SsmdBundleIndex, selector: str | None) -> tuple[BundleItem, ...]:
    """Select bundle items by source number while preserving manifest order."""
    selected = "all" if selector is None else selector.strip()
    if not selected:
        raise SsmdBundleError("chapter selector must not be empty")
    if index.kind == "document":
        if selected != "all":
            raise SsmdBundleError("document bundles only support --chapters all")
        return index.items
    if selected == "all":
        return index.items

    intervals: list[tuple[int, int]] = []
    for token in selected.split(","):
        token = token.strip()
        if not token:
            raise SsmdBundleError(f"malformed chapter selector: {selected!r}")
        if "-" in token:
            if token.count("-") != 1:
                raise SsmdBundleError(f"malformed chapter range: {token!r}")
            first_text, last_text = (part.strip() for part in token.split("-", 1))
            first = _parse_positive_number(first_text, selected)
            last = _parse_positive_number(last_text, selected)
            if first > last:
                raise SsmdBundleError(f"reversed chapter range: {token!r}")
            intervals.append((first, last))
        else:
            number = _parse_positive_number(token, selected)
            intervals.append((number, number))

    merged: list[tuple[int, int]] = []
    for first, last in sorted(intervals):
        if merged and first <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], last))
        else:
            merged.append((first, last))

    available = sorted(item.source_number for item in index.items)
    selected_numbers: set[int] = set()
    for first, last in merged:
        next_expected = first
        for number in available:
            if number < first:
                continue
            if number > last:
                break
            if number > next_expected:
                raise SsmdBundleError(
                    f"chapter selector references missing source number(s): {next_expected}"
                )
            selected_numbers.add(number)
            next_expected = number + 1
        if next_expected <= last:
            raise SsmdBundleError(
                f"chapter selector references missing source number(s): {next_expected}"
            )
    return tuple(item for item in index.items if item.source_number in selected_numbers)


def _parse_positive_number(value: str, selector: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise SsmdBundleError(f"malformed chapter selector: {selector!r}")
    try:
        number = int(value)
    except ValueError as exc:
        raise SsmdBundleError(f"malformed chapter selector: {selector!r}") from exc
    if number <= 0:
        raise SsmdBundleError("chapter numbers in selector must be positive integers")
    return number


def _not_bundle_root(path: str | Path) -> SsmdBundleError:
    return SsmdBundleError(
        f"not a canonical SSMD bundle root: {path}\n"
        "expected a directory named NAME.ssmd-bundle containing manifest.json"
    )


def resolve_ssmd_bundle_root(path: str | Path) -> Path:
    """Resolve *path* and require a canonical ``NAME.ssmd-bundle/`` root."""
    input_path = Path(path).expanduser()
    try:
        root = input_path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise _not_bundle_root(path) from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise SsmdBundleError(f"cannot inspect bundle root {input_path}: {exc}") from exc

    if not root.is_dir():
        raise _not_bundle_root(path)
    if not root.name.endswith(".ssmd-bundle") or root.name == ".ssmd-bundle":
        raise _not_bundle_root(path)

    manifest_path = root / "manifest.json"
    if not manifest_path.exists() and not manifest_path.is_symlink():
        raise _not_bundle_root(path)
    return root


def bundle_item_path(
    index: SsmdBundleIndex, item: BundleItem, *, require_exists: bool = False
) -> Path:
    """Resolve an item path while preventing traversal and symlink escapes."""
    _validate_item_path(index.kind, item.relative_path)
    source = index.root.joinpath(*PurePosixPath(item.relative_path).parts)
    try:
        resolved = source.resolve(strict=require_exists)
        resolved.relative_to(index.root)
        exists_or_link = source.exists() or source.is_symlink()
        if exists_or_link and not resolved.is_file():
            raise SsmdBundleError(f"bundle item is not a regular file: {item.relative_path}")
        if require_exists and not resolved.is_file():
            raise SsmdBundleError(f"bundle item is not a regular file: {item.relative_path}")
        if (
            index.kind == "document"
            and exists_or_link
            and resolved.stat().st_size > _MAX_DOCUMENT_BYTES
        ):
            raise SsmdBundleError("bundle document exceeds the 64 MiB size limit")
    except SsmdBundleError:
        raise
    except FileNotFoundError as exc:
        raise SsmdBundleError(f"bundle item is missing: {item.relative_path}") from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise SsmdBundleError(
            f"bundle item path escapes workspace root: {item.relative_path}"
        ) from exc
    return source


def _read_manifest(manifest_path: Path, root: Path) -> dict[str, Any]:
    if manifest_path.is_symlink():
        raise SsmdBundleError(
            f"bundle manifest must be a regular file, not a symlink: {manifest_path}"
        )
    try:
        resolved = manifest_path.resolve(strict=True)
        resolved.relative_to(root)
        if not resolved.is_file():
            raise SsmdBundleError(f"bundle manifest is not a regular file: {manifest_path}")
        if resolved.stat().st_size > _MAX_MANIFEST_BYTES:
            raise SsmdBundleError("bundle manifest.json exceeds the 2 MiB size limit")
        with resolved.open("rb") as stream:
            raw = stream.read(_MAX_MANIFEST_BYTES + 1)
    except SsmdBundleError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise SsmdBundleError(f"cannot read bundle manifest {manifest_path}: {exc}") from exc
    if len(raw) > _MAX_MANIFEST_BYTES:
        raise SsmdBundleError("bundle manifest.json exceeds the 2 MiB size limit")
    try:
        data = json.loads(raw.decode("utf-8"), parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise SsmdBundleError(f"invalid bundle manifest.json: {exc}") from exc
    if not isinstance(data, dict):
        raise SsmdBundleError("bundle manifest root must be a JSON object")
    return data


def _validate_header(data: dict[str, Any], *, expected_format: str) -> None:
    if type(data.get("schema_version")) is not int or data["schema_version"] != _SCHEMA_VERSION:
        raise SsmdBundleError("unsupported bundle schema_version; expected 1")
    if data.get("ssmd_version") != _SSMD_VERSION:
        raise SsmdBundleError("unsupported bundle ssmd_version; expected '0.9'")
    if data.get("format") != expected_format:
        raise SsmdBundleError(f"unsupported bundle format; expected {expected_format!r}")


def _book_items(data: dict[str, Any]) -> tuple[BundleItem, ...]:
    entries = data.get("chapters")
    if not isinstance(entries, list):
        raise SsmdBundleError("bundle manifest chapters must be an array")
    items: list[BundleItem] = []
    seen_ids: set[str] = set()
    seen_numbers: set[int] = set()
    seen_paths: set[str] = set()
    for position, entry in enumerate(entries):
        label = f"chapters[{position}]"
        if not isinstance(entry, dict):
            raise SsmdBundleError(f"{label} must be an object")
        item_id = entry.get("id")
        source_number = entry.get("source_number")
        relative_path = entry.get("path")
        title = entry.get("title")
        digest = entry.get("sha256")
        if not isinstance(item_id, str) or not item_id.strip():
            raise SsmdBundleError(f"{label}.id must be a non-empty string")
        if type(source_number) is not int or source_number <= 0:
            raise SsmdBundleError(f"{label}.source_number must be a positive integer")
        if not isinstance(relative_path, str) or not relative_path:
            raise SsmdBundleError(
                f"{label}.path must be a non-empty normalized relative POSIX path"
            )
        _validate_item_path("book", relative_path, label=f"{label}.path")
        if not isinstance(title, str):
            raise SsmdBundleError(f"{label}.title must be a string")
        if digest is not None and not isinstance(digest, str):
            raise SsmdBundleError(f"{label}.sha256 must be a string when present")
        if item_id in seen_ids:
            raise SsmdBundleError(f"duplicate bundle item id: {item_id}")
        if source_number in seen_numbers:
            raise SsmdBundleError(f"duplicate bundle source_number: {source_number}")
        if relative_path in seen_paths:
            raise SsmdBundleError(f"duplicate bundle item path: {relative_path}")
        seen_ids.add(item_id)
        seen_numbers.add(source_number)
        seen_paths.add(relative_path)
        items.append(BundleItem(item_id, relative_path, source_number, title, digest))
    return tuple(items)


def _document_items(data: dict[str, Any]) -> tuple[BundleItem, ...]:
    document = data.get("document")
    if not isinstance(document, dict):
        raise SsmdBundleError("bundle manifest document must be an object")
    item_id = document.get("id")
    relative_path = document.get("path")
    if not isinstance(item_id, str) or not item_id.strip():
        raise SsmdBundleError("document.id must be a non-empty string")
    if not isinstance(relative_path, str) or not relative_path:
        raise SsmdBundleError("document.path must be a non-empty normalized relative POSIX path")
    _validate_item_path("document", relative_path, label="document.path")
    digest = document.get("sha256")
    if digest is not None and (not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None):
        raise SsmdBundleError("document.sha256 must be 64 lowercase hexadecimal characters")
    if "char_count" in document:
        char_count = document["char_count"]
        if type(char_count) is not int or char_count < 0:
            raise SsmdBundleError("document.char_count must be a non-negative integer")
    metadata = data.get("metadata")
    title = metadata.get("title") if isinstance(metadata, dict) else None
    if title is not None and not isinstance(title, str):
        raise SsmdBundleError("document metadata title must be a string when present")
    return (BundleItem(item_id, relative_path, 1, title, digest),)


def _validate_item_path(kind: BundleKind, value: str, *, label: str = "bundle item path") -> None:
    if "\x00" in value:
        raise SsmdBundleError(f"{label} must not contain NUL")
    if "\\" in value:
        raise SsmdBundleError(f"{label} must use normalized POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or PureWindowsPath(value).drive:
        raise SsmdBundleError(f"{label} must be a relative POSIX path")
    if not path.parts or any(part in {"", ".", ".."} for part in value.split("/")):
        raise SsmdBundleError(f"{label} must not contain empty, '.' or '..' path components")
    if path.as_posix() != value:
        raise SsmdBundleError(f"{label} must be a normalized relative POSIX path")
    if kind == "book" and (not value.startswith("chapters/") or len(path.parts) < 2):
        raise SsmdBundleError(f"{label} must be a normalized path below 'chapters/'")


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-standard JSON constant {value!r}")


__all__ = [
    "BundleItem",
    "BundleKind",
    "SsmdBundleError",
    "SsmdBundleIndex",
    "bundle_item_path",
    "load_ssmd_bundle",
    "select_bundle_items",
    "resolve_ssmd_bundle_root",
]
