"""Centralized path loading for standalone documents and SSMDDoc workspaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .compiler import InputFormat
from .ssmdoc import SSMDDocError, load_ssmdoc_index, ssmdoc_document_path

RequestedInputFormat = Literal["auto", "plain", "ssmd"]


class SourceInputError(ValueError):
    """A source path is unsupported or conflicts with its declared format."""


@dataclass(frozen=True, slots=True)
class LoadedSourceInput:
    """Decoded source text and its resolved format/path provenance."""

    text: str
    input_format: InputFormat
    source_path: Path
    source_label: str
    workspace_root: Path | None = None
    workspace_kind: Literal["ssmdoc"] | None = None


def load_source_path(
    path: str | Path,
    *,
    requested_format: RequestedInputFormat = "auto",
) -> LoadedSourceInput:
    """Read a source file or current document from an SSMDDoc workspace."""
    input_path = Path(path).expanduser()
    workspace_root: Path | None = None
    workspace_kind: Literal["ssmdoc"] | None = None

    if input_path.is_dir():
        try:
            index = load_ssmdoc_index(input_path)
            source_path = ssmdoc_document_path(index)
        except SSMDDocError as exc:
            if isinstance(exc.__cause__, FileNotFoundError):
                raise exc.__cause__ from None
            raise SourceInputError(f"unsupported source directory {input_path}: {exc}") from exc
        workspace_root = index.root
        workspace_kind = "ssmdoc"
    elif input_path.name == "document.ssmd.md" and _manifest_exists(input_path.parent):
        index = load_ssmdoc_index(input_path)
        source_path = ssmdoc_document_path(index)
        workspace_root = index.root
        workspace_kind = "ssmdoc"
    else:
        source_path = input_path
        if not source_path.is_file():
            raise SourceInputError(f"source path is not a regular file: {source_path}")

    if workspace_kind is not None:
        if requested_format == "plain":
            raise SourceInputError(
                "SSMDDoc workspace input is SSMD; --input-format plain is not supported"
            )
        input_format: InputFormat = "ssmd"
    else:
        text = source_path.read_text(encoding="utf-8")
        input_format = _format_for_path(source_path, text, requested_format)
        return LoadedSourceInput(
            text=text,
            input_format=input_format,
            source_path=source_path,
            source_label=str(source_path),
        )

    text = source_path.read_text(encoding="utf-8")
    return LoadedSourceInput(
        text=text,
        input_format=input_format,
        source_path=source_path,
        source_label=str(source_path),
        workspace_root=workspace_root,
        workspace_kind=workspace_kind,
    )


def _manifest_exists(root: Path) -> bool:
    manifest_path = root / "manifest.json"
    return manifest_path.exists() or manifest_path.is_symlink()


def _format_for_path(
    path: Path, source: str, requested_format: RequestedInputFormat
) -> InputFormat:
    if requested_format != "auto":
        return requested_format
    lower_name = path.name.lower()
    if lower_name.endswith((".ssmd.md", ".ssmd")):
        return "ssmd"
    if path.suffix.lower() == ".md" and _declares_ssmd_version(source):
        return "ssmd"
    return "plain"


def _declares_ssmd_version(source: str) -> bool:
    try:
        from ssmd.frontmatter import FrontMatterError, parse_front_matter
    except ImportError:
        return False
    try:
        front_matter = parse_front_matter(source)
    except FrontMatterError:
        return False
    return front_matter.present and "ssmd_version" in front_matter.data


__all__ = [
    "LoadedSourceInput",
    "RequestedInputFormat",
    "SourceInputError",
    "load_source_path",
]
