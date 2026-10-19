from __future__ import annotations

import pytest
from renderplan import PausePolicy, PlanningPolicy, RenderProfile, RoleProfile

from utterplan import (
    AudioDirective,
    FlowPlan,
    FlowSegment,
    FlowUnit,
    SegmentDirectives,
    VoiceDirective,
    assert_profile_role_coverage,
    logical_role_inventory,
    profile_role_coverage,
)
from utterplan.renderplan_projection import RenderPlanProjectionError


def _plan(*segments: FlowSegment) -> FlowPlan:
    return FlowPlan(language="en-US", flow=(FlowUnit(tuple(segments)),))


def _profile(roles: dict[str, RoleProfile], *, default_role: str = "narrator") -> RenderProfile:
    return RenderProfile(
        roles=roles,
        default_role=default_role,
        planning=PlanningPolicy(split="sentence"),
        pauses=PausePolicy(mode="manual"),
    )


def _role(reference: str) -> SegmentDirectives:
    return SegmentDirectives(voice=VoiceDirective(reference=reference))


def test_inventory_counts_explicit_roles_in_first_occurrence_order_and_skips_non_speech() -> None:
    plan = _plan(
        FlowSegment("Narration.", "en-US", directives=_role("narrator")),
        FlowSegment("Host.", "en-US", directives=_role("host")),
        FlowSegment("Guest.", "en-US", directives=_role("guest")),
        FlowSegment("Host again.", "en-US", directives=_role("host")),
        FlowSegment("Default.", "en-US"),
        FlowSegment("", "en-US", directives=_role("empty")),
        FlowSegment(
            "audio alternative",
            "en-US",
            directives=SegmentDirectives(audio=AudioDirective(src="music.wav")),
        ),
    )

    inventory = logical_role_inventory(plan)

    assert inventory.explicit_roles == ("narrator", "host", "guest")
    assert dict(inventory.explicit_occurrences) == {"narrator": 1, "host": 2, "guest": 1}
    assert inventory.uses_default_role is True
    assert inventory.implicit_occurrences == 1


def test_profile_coverage_uses_first_occurrence_and_default_role_and_allows_extra_roles() -> None:
    plan = _plan(
        FlowSegment("Host.", "en-US", directives=_role("host")),
        FlowSegment("Guest.", "en-US", directives=_role("guest")),
        FlowSegment("Narration.", "en-US"),
    )
    profile = _profile(
        {
            "narrator": RoleProfile(language="en-US", binding={"renderer": "kokoro"}),
            "host": RoleProfile(language="en-US", binding={"renderer": "kitten"}),
            "guest": RoleProfile(language="en-US", binding={"renderer": "piper"}),
            "unused": RoleProfile(language="en-US", binding={"renderer": "other"}),
        }
    )

    coverage = assert_profile_role_coverage(plan, profile)

    assert coverage.default_role == "narrator"
    assert coverage.explicit_roles == ("host", "guest")
    assert coverage.required_roles == ("host", "guest", "narrator")
    assert coverage.available_roles == ("guest", "host", "narrator", "unused")
    assert coverage.missing_roles == ()
    assert coverage.uses_default_role is True


def test_explicit_roles_do_not_require_unused_profile_default() -> None:
    plan = _plan(
        FlowSegment("Host.", "en-US", directives=_role("host")),
        FlowSegment("Guest.", "en-US", directives=_role("guest")),
    )
    profile = _profile(
        {
            "narrator": RoleProfile(language="en-US", binding={"renderer": "kokoro"}),
            "host": RoleProfile(language="en-US", binding={"renderer": "kitten"}),
            "guest": RoleProfile(language="en-US", binding={"renderer": "piper"}),
        }
    )

    coverage = profile_role_coverage(plan, profile)

    assert coverage.required_roles == ("host", "guest")
    assert coverage.available_roles == ("guest", "host", "narrator")
    assert coverage.missing_roles == ()
    assert coverage.uses_default_role is False


def test_missing_explicit_roles_are_aggregated_in_one_error() -> None:
    plan = _plan(
        FlowSegment("Guest.", "en-US", directives=_role("guest")),
        FlowSegment("Host.", "en-US", directives=_role("host")),
        FlowSegment("Default.", "en-US"),
    )
    profile = _profile(
        {
            "narrator": RoleProfile(language="en-US", binding={"renderer": "fixture"}),
            "extra": RoleProfile(language="en-US", binding={"renderer": "fixture"}),
        }
    )

    coverage = profile_role_coverage(plan, profile)
    with pytest.raises(RenderPlanProjectionError) as raised:
        assert_profile_role_coverage(plan, profile)

    assert coverage.required_roles == ("guest", "host", "narrator")
    assert coverage.missing_roles == ("guest", "host")
    assert raised.value.code == "renderplan.role.missing"
    assert "guest, host" in str(raised.value)
