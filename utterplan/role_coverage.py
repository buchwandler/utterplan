"""Renderer-independent logical voice-role inventory and profile coverage."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from renderplan import RenderProfile

from .model import FlowPlan
from .renderplan_projection import RenderPlanProjectionError


@dataclass(frozen=True, slots=True)
class LogicalRoleInventory:
    """Logical roles explicitly used by speech and speech using the profile default."""

    explicit_roles: tuple[str, ...]
    uses_default_role: bool
    explicit_occurrences: Mapping[str, int]
    implicit_occurrences: int


@dataclass(frozen=True, slots=True)
class ProfileRoleCoverage:
    """Required logical roles compared with the roles in one RenderProfile."""

    default_role: str
    required_roles: tuple[str, ...]
    available_roles: tuple[str, ...]
    missing_roles: tuple[str, ...]
    explicit_roles: tuple[str, ...]
    uses_default_role: bool


def logical_role_inventory(plan: FlowPlan) -> LogicalRoleInventory:
    """Inspect speech segments in source order without resolving any concrete voices."""
    occurrences: dict[str, int] = {}
    implicit_occurrences = 0

    for unit in plan.flow:
        for segment in unit.segments:
            if not segment.text or segment.directives.audio is not None:
                continue
            voice = segment.directives.voice
            role = voice.reference if voice is not None else None
            if role:
                occurrences[role] = occurrences.get(role, 0) + 1
            else:
                implicit_occurrences += 1

    return LogicalRoleInventory(
        explicit_roles=tuple(occurrences),
        uses_default_role=implicit_occurrences > 0,
        explicit_occurrences=MappingProxyType(occurrences),
        implicit_occurrences=implicit_occurrences,
    )


def profile_role_coverage(plan: FlowPlan, profile: RenderProfile) -> ProfileRoleCoverage:
    """Return deterministic required/available/missing roles for a source and profile."""
    inventory = logical_role_inventory(plan)
    required = list(inventory.explicit_roles)
    if inventory.uses_default_role and profile.default_role not in required:
        required.append(profile.default_role)

    available = tuple(sorted(profile.roles))
    available_set = set(available)
    required_roles = tuple(required)
    return ProfileRoleCoverage(
        default_role=profile.default_role,
        required_roles=required_roles,
        available_roles=available,
        missing_roles=tuple(role for role in required_roles if role not in available_set),
        explicit_roles=inventory.explicit_roles,
        uses_default_role=inventory.uses_default_role,
    )


def assert_profile_role_coverage(plan: FlowPlan, profile: RenderProfile) -> ProfileRoleCoverage:
    """Return complete profile coverage or raise one aggregate projection error."""
    coverage = profile_role_coverage(plan, profile)
    if coverage.missing_roles:
        raise RenderPlanProjectionError(
            "RenderProfile does not cover logical voice roles: "
            + ", ".join(coverage.missing_roles),
            code="renderplan.role.missing",
        )
    return coverage


__all__ = [
    "LogicalRoleInventory",
    "ProfileRoleCoverage",
    "assert_profile_role_coverage",
    "logical_role_inventory",
    "profile_role_coverage",
]
