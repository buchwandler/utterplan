"""Read-only discovery and safe path resolution for editable SSMDDoc workspaces."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

_DOCUMENT_FORMAT = "ssmdconvert.document"
_DOCUMENT_SCHEMA_VERSION = 1
_SSMD_VERSION = "0.9"
_DOCUMENT_ID = "document-0001"
_DOCUMENT_PATH = "document.ssmd.md"
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_DOCUMENT_BYTES = 64 * 1024 * 1024
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class SSMDDocError(ValueError):
    """An SSMDDoc workspace is invalid or unsafe."""


@dataclass(frozen=True, slots=True)
class SSMDDocIndex:
    """Validated, read-only document-workspace manifest data."""

    root: Path
    manifest_path: Path
    document_id: str
    relative_path: str
    expected_sha256: str
    expected_char_count: int


def resolve_ssmdoc_root(path: str | Path) -> Path:
    """Resolve a manifest-authorized workspace root or its canonical document path."""
    input_path = Path(path).expanduser()
    try:
        if input_path.is_dir():
            root = input_path.resolve(strict=True)
            if _has_document_manifest(root):
                return root
        elif input_path.name == _DOCUMENT_PATH and input_path.parent.is_dir():
            root = input_path.parent.resolve(strict=True)
            if _has_document_manifest(root):
                return root
    except SSMDDocError:
        raise
    except (OSError, RuntimeError) as exc:
        raise SSMDDocError(f"cannot inspect ssmdoc input {input_path}: {exc}") from exc

    raise SSMDDocError(
        f"not an ssmdoc workspace: {path}\n"
        "expected manifest.json with format 'ssmdconvert.document'"
    )


def load_ssmdoc_index(path: str | Path) -> SSMDDocIndex:
    """Read and validate the public SSMDDoc v1 manifest without reading the document."""
    root = resolve_ssmdoc_root(path)
    manifest_path = root / "manifest.json"
    data = _read_manifest(root)

    if data.get("format") != _DOCUMENT_FORMAT:
        raise SSMDDocError("unsupported ssmdoc format; expected 'ssmdconvert.document'")
    schema_version = data.get("schema_version")
    if type(schema_version) is not int or schema_version != _DOCUMENT_SCHEMA_VERSION:
        raise SSMDDocError("unsupported ssmdoc schema_version; expected 1")
    if data.get("ssmd_version") != _SSMD_VERSION:
        raise SSMDDocError("unsupported ssmdoc ssmd_version; expected '0.9'")

    document = data.get("document")
    if not isinstance(document, dict):
        raise SSMDDocError("ssmdoc manifest document must be an object")
    document_id = document.get("id")
    relative_path = document.get("path")
    expected_sha256 = document.get("sha256")
    expected_char_count = document.get("char_count")

    if document_id != _DOCUMENT_ID:
        raise SSMDDocError(f"unsupported ssmdoc document.id; expected '{_DOCUMENT_ID}'")
    if not isinstance(relative_path, str) or not relative_path:
        raise SSMDDocError(
            "ssmdoc document.path must be a non-empty normalized relative POSIX path"
        )
    _validate_relative_document_path(relative_path)
    if relative_path != _DOCUMENT_PATH:
        raise SSMDDocError(f"unsupported ssmdoc document.path; expected '{_DOCUMENT_PATH}'")
    if not isinstance(expected_sha256, str) or _SHA256_RE.fullmatch(expected_sha256) is None:
        raise SSMDDocError("ssmdoc document.sha256 must be 64 lowercase hexadecimal characters")
    if type(expected_char_count) is not int or expected_char_count < 0:
        raise SSMDDocError("ssmdoc document.char_count must be a non-negative integer")

    return SSMDDocIndex(
        root=root,
        manifest_path=manifest_path,
        document_id=document_id,
        relative_path=relative_path,
        expected_sha256=expected_sha256,
        expected_char_count=expected_char_count,
    )


def ssmdoc_document_path(index: SSMDDocIndex) -> Path:
    """Return the canonical document path after enforcing containment and file safety."""
    _validate_relative_document_path(index.relative_path)
    if index.relative_path != _DOCUMENT_PATH:
        raise SSMDDocError(f"unsupported ssmdoc document.path; expected '{_DOCUMENT_PATH}'")

    try:
        root = index.root.resolve(strict=True)
        source = root.joinpath(*PurePosixPath(index.relative_path).parts)
        resolved = source.resolve(strict=False)
        resolved.relative_to(root)
        exists_or_link = source.exists() or source.is_symlink()
        if exists_or_link:
            if not resolved.is_file():
                raise SSMDDocError(f"ssmdoc document is not a regular file: {index.relative_path}")
            if resolved.stat().st_size > _MAX_DOCUMENT_BYTES:
                raise SSMDDocError("ssmdoc document.ssmd.md exceeds the 64 MiB size limit")
    except SSMDDocError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise SSMDDocError(
            f"ssmdoc document path escapes workspace root: {index.relative_path}"
        ) from exc
    return source


def _has_document_manifest(root: Path) -> bool:
    manifest_path = root / "manifest.json"
    if not manifest_path.exists() and not manifest_path.is_symlink():
        return False
    data = _read_manifest(root)
    return data.get("format") == _DOCUMENT_FORMAT


def _read_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    try:
        resolved_manifest = manifest_path.resolve(strict=True)
        resolved_manifest.relative_to(root)
        if not resolved_manifest.is_file():
            raise SSMDDocError(f"ssmdoc manifest is not a regular file: {manifest_path}")
        if resolved_manifest.stat().st_size > _MAX_MANIFEST_BYTES:
            raise SSMDDocError("ssmdoc manifest.json exceeds the 2 MiB size limit")
        with resolved_manifest.open("rb") as stream:
            raw = stream.read(_MAX_MANIFEST_BYTES + 1)
    except SSMDDocError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise SSMDDocError(f"cannot read ssmdoc manifest {manifest_path}: {exc}") from exc

    if len(raw) > _MAX_MANIFEST_BYTES:
        raise SSMDDocError("ssmdoc manifest.json exceeds the 2 MiB size limit")
    try:
        data = json.loads(raw.decode("utf-8"), parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise SSMDDocError(f"invalid ssmdoc manifest.json: {exc}") from exc
    if not isinstance(data, dict):
        raise SSMDDocError("ssmdoc manifest root must be a JSON object")
    return data


def _validate_relative_document_path(value: str) -> None:
    if "\x00" in value:
        raise SSMDDocError("ssmdoc document.path must not contain NUL")
    if "\\" in value:
        raise SSMDDocError("ssmdoc document.path must use normalized POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or PureWindowsPath(value).drive:
        raise SSMDDocError("ssmdoc document.path must be a relative POSIX path")
    if any(part in {".", ".."} for part in path.parts):
        raise SSMDDocError("ssmdoc document.path must not contain '.' or '..' components")
    if path.as_posix() != value:
        raise SSMDDocError("ssmdoc document.path must be a normalized relative POSIX path")


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-standard JSON constant {value!r}")


__all__ = [
    "SSMDDocError",
    "SSMDDocIndex",
    "load_ssmdoc_index",
    "resolve_ssmdoc_root",
    "ssmdoc_document_path",
]
