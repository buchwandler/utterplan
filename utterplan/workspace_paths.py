"""Shared filename helpers for workspace-local derived artifacts."""

from __future__ import annotations

from pathlib import Path


def source_output_stem(source: Path) -> str:
    """Return the portable artifact stem for an SSMD source path."""
    lower_name = source.name.lower()
    for suffix in (".ssmd.md", ".ssmd", ".md"):
        if lower_name.endswith(suffix):
            return source.name[: -len(suffix)]
    return source.stem


def utterplan_output_name(source: Path) -> str:
    """Return the canonical UtterPlan filename for an SSMD source."""
    return f"{source_output_stem(source)}.utterplan.toml"


def renderplan_output_name(source: Path) -> str:
    """Return the canonical RenderPlan filename for an SSMD source."""
    return f"{source_output_stem(source)}.renderplan.toml"


__all__ = ["renderplan_output_name", "source_output_stem", "utterplan_output_name"]
