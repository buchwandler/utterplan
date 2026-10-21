"""Centralized path loading for standalone source files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .compiler import InputFormat

RequestedInputFormat = Literal["auto", "plain", "ssmd"]


class SourceInputError(ValueError):
    """A standalone source path is unsupported or conflicts with its declared format."""


@dataclass(frozen=True, slots=True)
class LoadedSourceInput:
    """Decoded source text and its resolved format/path provenance."""

    text: str
    input_format: InputFormat
    source_path: Path
    source_label: str


def load_source_path(
    path: str | Path,
    *,
    requested_format: RequestedInputFormat = "auto",
) -> LoadedSourceInput:
    """Read one standalone source file; bundle discovery belongs to bundle commands."""
    source_path = Path(path).expanduser()
    if not source_path.is_file():
        raise SourceInputError(f"source path is not a regular file: {source_path}")
    text = source_path.read_text(encoding="utf-8")
    input_format = _format_for_path(source_path, text, requested_format)
    return LoadedSourceInput(
        text=text,
        input_format=input_format,
        source_path=source_path,
        source_label=str(source_path),
    )


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
