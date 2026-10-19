"""Shared profile variant naming for workspace RenderPlan projections."""
from __future__ import annotations

import re
from pathlib import Path


def render_variant_label(profile_path: Path, override: str | None = None) -> str:
    if override is None:
        name = profile_path.name
        suffix = ".renderprofile.toml"
        raw_label = name[: -len(suffix)] if name.lower().endswith(suffix) else profile_path.stem
    else:
        raw_label = override
    return re.sub(r"[^a-z0-9_.-]+", "-", raw_label.lower()).strip("._-") or "profile"


def profile_fingerprint(profile_id: str) -> str:
    return profile_id.removeprefix("sha256:")[:12]


__all__ = ["profile_fingerprint", "render_variant_label"]
