from __future__ import annotations

from dataclasses import replace

import pytest
from renderplan import (
    AudioItem,
    CapacityConstraint,
    PauseItem,
    PausePolicy,
    PlanningPolicy,
    RenderProfile,
    RoleProfile,
    SourceSpan,
    SpeechItem,
)

from utterplan import (
    AudioDirective,
    EmphasisDirective,
    ExtensionDirective,
    FlowPlan,
    FlowSegment,
    FlowUnit,
    LegacyFlowPlan,
    PauseIntent,
    PlannerConfig,
    ProsodyDirective,
    SegmentDirectives,
    TokenView,
    VoiceDirective,
    build_render_plan,
    compile_document,
)
from utterplan.hashing import V5_FLOW_HASH_SCHEMA, V6_FLOW_HASH_SCHEMA
from utterplan.renderplan_grouping import group_initial_plan
from utterplan.renderplan_projection import (
    RenderPlanProjectionError,
    build_source_index,
)


def _legacy_plan(version: int) -> LegacyFlowPlan:
    hash_schema = V5_FLOW_HASH_SCHEMA if version == 5 else V6_FLOW_HASH_SCHEMA
    return LegacyFlowPlan(
        language="en-US",
        flow=(FlowUnit((FlowSegment("Legacy.", "en-US"),)),),
        schema_version=version,
        hash_schema=hash_schema,
    )


def _projection_plan() -> FlowPlan:
    return FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        "Say ",
                        "en-US",
                        directives=SegmentDirectives(emphasis=EmphasisDirective("strong")),
                        tokens=(TokenView(0, 3, lemma="say", pos="VERB", tag="VB"),),
                    ),
                    FlowSegment(
                        " hello.",
                        "en-US",
                        directives=SegmentDirectives(
                            prosody=ProsodyDirective(rate="slow"),
                            extensions=(ExtensionDirective("x-accent", {"value": "bright"}),),
                        ),
                        tokens=(TokenView(1, 6, lemma="hello", pos="NOUN", tag="NN"),),
                    ),
                )
            ),
            FlowUnit((FlowSegment(" Again.", "en-US"),)),
        ),
    )


def test_renderplan_source_index_rejects_v5_and_v6_legacy_plans() -> None:
    for version in (5, 6):
        with pytest.raises(
            RenderPlanProjectionError, match=f"legacy schema version {version}"
        ) as error:
            build_source_index(_legacy_plan(version))  # type: ignore[arg-type]
        assert error.value.code == "renderplan.source.schema_version"


def test_v7_source_index_uses_deterministic_zero_based_locators() -> None:
    plan = _projection_plan()

    first = build_source_index(plan)
    second = build_source_index(plan)

    assert [ref.locator for ref in first.ordered_refs] == [
        "f000000.s000",
        "f000000.s001",
        "f000001.s000",
    ]
    assert first.ordered_refs == second.ordered_refs
    assert first.source_plan_id == plan.plan_id
    assert first.resolve("f000001.s000").segment.text == " Again."


def test_exact_source_text_tokens_and_controls_rebase_without_trimming() -> None:
    index = build_source_index(_projection_plan())
    source = (
        SourceSpan("f000000.s000", 0, 4),
        SourceSpan("f000000.s001", 0, 7),
    )

    assert index.text_for(source) == "Say  hello."
    tokens = index.tokens_for(source, required_fields=("span", "pos", "lemma"))
    assert tokens is not None
    assert tokens.span == ((0, 3), (5, 10))
    assert tokens.pos == ("VERB", "NOUN")
    assert tokens.tag == ("VB", "NN")
    assert tokens.lemma == ((0, "say"), (1, "hello"))
    assert index.controls_for(source) == tuple(
        sorted(index.controls_for(source), key=lambda control: control.ordering_key())
    )
    assert [(item.start, item.end, item.name) for item in index.controls_for(source)] == [
        (0, 4, "emphasis"),
        (4, 11, "extension"),
        (4, 11, "prosody"),
    ]
    assert dict(index.controls_for(source)[2].params) == {"rate": "slow"}
    assert dict(index.controls_for(source)[1].params) == {
        "name": "x-accent",
        "value": "bright",
    }


def test_sparse_optional_morphology_is_preserved_but_required_morph_fails() -> None:
    plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        "read the book",
                        "en-US",
                        tokens=(
                            TokenView(0, 4, lemma="read", morph="Tense=Pres"),
                            TokenView(5, 8, lemma="the"),
                            TokenView(9, 13, lemma="book", morph="Number=Sing"),
                        ),
                    ),
                )
            ),
        ),
    )
    index = build_source_index(plan)
    source = (SourceSpan("f000000.s000", 0, 13),)

    optional = index.tokens_for(source, required_fields=())
    assert optional is not None
    assert optional.morph == ((0, "Tense=Pres"), (2, "Number=Sing"))

    with pytest.raises(RenderPlanProjectionError, match="required token field 'morph'") as error:
        index.tokens_for(source, required_fields=("morph",))
    assert error.value.code == "renderplan.token.required"
    assert error.value.locator == "f000000.s000"
    assert error.value.token_index == 1


def test_partial_token_slice_and_missing_required_field_fail_with_locator() -> None:
    index = build_source_index(_projection_plan())

    with pytest.raises(RenderPlanProjectionError, match="cuts token") as split_error:
        index.tokens_for((SourceSpan("f000000.s000", 1, 4),))
    assert split_error.value.code == "renderplan.token.split"
    assert split_error.value.locator == "f000000.s000"
    assert split_error.value.token_index == 0

    incomplete = FlowPlan(
        language="en-US",
        flow=(FlowUnit((FlowSegment("Hello", "en-US", tokens=(TokenView(0, 5),)),)),),
    )
    with pytest.raises(RenderPlanProjectionError, match="required token field 'pos'") as error:
        build_source_index(incomplete).tokens_for(
            (SourceSpan("f000000.s000", 0, 5),), required_fields=("pos",)
        )
    assert error.value.locator == "f000000.s000"
    assert error.value.token_index == 0


def test_source_index_rejects_unknown_and_out_of_range_source_spans() -> None:
    index = build_source_index(_projection_plan())

    with pytest.raises(RenderPlanProjectionError) as unknown:
        index.text_for((SourceSpan("f000003.s000", 0, 1),))
    assert unknown.value.code == "renderplan.source.locator"

    with pytest.raises(RenderPlanProjectionError) as out_of_range:
        index.text_for((SourceSpan("f000000.s000", 0, 5),))
    assert out_of_range.value.code == "renderplan.source.range"


def _profile(
    *,
    split: str = "sentence",
    roles: dict[str, RoleProfile] | None = None,
    pauses: dict[str, int] | None = None,
    fallback: tuple[str, ...] = ("clause", "token"),
) -> RenderProfile:
    role_map = roles or {"narrator": RoleProfile(language="en-US", binding={"engine": "fixture"})}
    default_role = "narrator"
    return RenderProfile(
        roles=role_map,
        default_role=default_role,
        planning=PlanningPolicy(split=split, capacity_fallback=fallback),
        pauses=PausePolicy(mode="manual", durations_ms=pauses or {}),
    )


def _group(plan: FlowPlan, profile: RenderProfile):
    return group_initial_plan(build_source_index(plan), profile)


def _parenthetical_plan(
    *,
    entry_pause: PauseIntent | None = None,
    exit_pause: PauseIntent | None = None,
) -> FlowPlan:
    return FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        "Before ",
                        "en-US",
                        tokens=(TokenView(0, 6),),
                        pause_after=entry_pause,
                        boundary_after=("parenthetical",),
                    ),
                    FlowSegment(
                        "(aside)",
                        "en-US",
                        directives=SegmentDirectives(emphasis=EmphasisDirective("strong")),
                        tokens=(TokenView(1, 6),),
                        boundary_before=("parenthetical",),
                        pause_after=exit_pause,
                        boundary_after=("parenthetical",),
                    ),
                    FlowSegment(
                        " after.",
                        "en-US",
                        tokens=(TokenView(1, 6),),
                        boundary_before=("parenthetical",),
                        boundary_after=("sentence",),
                    ),
                )
            ),
        ),
    )


def test_sentence_grouping_joins_exact_prepared_text_and_ignores_clause_boundaries() -> None:
    plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment("Obviously, ", "en-US", boundary_after=("clause",)),
                    FlowSegment("to make this plan work, ", "en-US", boundary_after=("clause",)),
                    FlowSegment("we had needed a suit.", "en-US", boundary_after=("sentence",)),
                )
            ),
        ),
    )

    flow = _group(plan, _profile(pauses={"sentence": 500}))

    assert [item.text for item in flow if isinstance(item, SpeechItem)] == [
        "Obviously, to make this plan work, we had needed a suit."
    ]
    assert [item.duration_ms for item in flow if isinstance(item, PauseItem)] == [500]
    assert next(item for item in flow if isinstance(item, PauseItem)).reason == "sentence"


def test_parenthetical_boundaries_remain_joined_when_pause_policy_is_unset() -> None:
    plan = _parenthetical_plan()
    profile = _profile(pauses={"sentence": 500})

    flow = _group(plan, profile)
    speech = [item for item in flow if isinstance(item, SpeechItem)]
    pauses = [item for item in flow if isinstance(item, PauseItem)]

    assert [item.text for item in speech] == ["Before (aside) after."]
    assert [item.semantic_end for item in speech] == ["sentence"]
    assert [(item.duration_ms, item.reason) for item in pauses] == [(500, "sentence")]
    assert _group(plan, profile) == flow


@pytest.mark.parametrize("duration", (180, 0))
def test_configured_parenthetical_edges_split_once_and_preserve_request_fidelity(
    duration: int,
) -> None:
    plan = _parenthetical_plan()
    profile = _profile(pauses={"parenthetical": duration, "sentence": 500})

    flow = _group(plan, profile)
    speech = [item for item in flow if isinstance(item, SpeechItem)]
    pauses = [item for item in flow if isinstance(item, PauseItem)]

    assert [type(item) for item in flow] == [
        SpeechItem,
        PauseItem,
        SpeechItem,
        PauseItem,
        SpeechItem,
        PauseItem,
    ]
    assert [item.text for item in speech] == ["Before ", "(aside)", " after."]
    assert [item.semantic_end for item in speech] == [
        "parenthetical",
        "parenthetical",
        "sentence",
    ]
    assert [(item.duration_ms, item.reason) for item in pauses] == [
        (duration, "parenthetical"),
        (duration, "parenthetical"),
        (500, "sentence"),
    ]
    assert "".join(item.text for item in speech) == "Before (aside) after."
    assert [item.source for item in speech] == [
        (SourceSpan("f000000.s000", 0, 7),),
        (SourceSpan("f000000.s001", 0, 7),),
        (SourceSpan("f000000.s002", 0, 7),),
    ]
    assert [item.tokens.span if item.tokens is not None else None for item in speech] == [
        ((0, 6),),
        ((1, 6),),
        ((1, 6),),
    ]
    assert [
        [(control.start, control.end, control.name) for control in item.controls] for item in speech
    ] == [[], [(0, 7, "emphasis")], []]
    assert _group(plan, profile) == flow


def test_parenthetical_policy_is_disabled_by_none_mode() -> None:
    plan = _parenthetical_plan()
    profile = _profile()
    profile = replace(
        profile,
        pauses=PausePolicy(mode="none", durations_ms={"parenthetical": 180}),
        profile_id=None,
    )

    flow = _group(plan, profile)

    assert [item.text for item in flow if isinstance(item, SpeechItem)] == ["Before (aside) after."]
    assert not any(isinstance(item, PauseItem) and item.reason == "parenthetical" for item in flow)


def test_authored_none_suppresses_only_parenthetical_policy_splits() -> None:
    plan = _parenthetical_plan(
        entry_pause=PauseIntent("none"),
        exit_pause=PauseIntent("none"),
    )
    profile = _profile(pauses={"parenthetical": 180, "sentence": 500})

    flow = _group(plan, profile)

    assert [item.text for item in flow if isinstance(item, SpeechItem)] == ["Before (aside) after."]
    assert [(item.duration_ms, item.reason) for item in flow if isinstance(item, PauseItem)] == [
        (500, "sentence")
    ]


def test_authored_none_resolves_coincident_sentence_parenthetical_edge() -> None:
    edge = ("sentence", "parenthetical")
    plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        "Before ",
                        "en-US",
                        pause_after=PauseIntent("none"),
                        boundary_after=edge,
                    ),
                    FlowSegment(
                        "(aside)",
                        "en-US",
                        boundary_before=edge,
                        boundary_after=("sentence",),
                    ),
                )
            ),
        ),
    )
    profile = _profile(pauses={"parenthetical": 180, "sentence": 500})

    flow = _group(plan, profile)
    speech = [item for item in flow if isinstance(item, SpeechItem)]
    pauses = [item for item in flow if isinstance(item, PauseItem)]

    assert [item.text for item in speech] == ["Before ", "(aside)"]
    assert speech[0].semantic_end == "sentence"
    assert [(item.duration_ms, item.reason) for item in pauses] == [
        (0, "authored_none"),
        (500, "sentence"),
    ]


@pytest.mark.parametrize(
    ("intent", "extra_pause", "expected"),
    (
        (PauseIntent("timed", "350ms"), {}, (350, "timed")),
        (PauseIntent("strong"), {"strong": 400}, (400, "strong")),
    ),
)
def test_authored_timed_and_named_pauses_win_at_parenthetical_edges(
    intent: PauseIntent,
    extra_pause: dict[str, int],
    expected: tuple[int, str],
) -> None:
    plan = _parenthetical_plan(entry_pause=intent)
    profile = _profile(pauses={"parenthetical": 180, **extra_pause})

    flow = _group(plan, profile)

    assert [
        (item.duration_ms, item.reason)
        for item in flow
        if isinstance(item, PauseItem) and item.reason != "sentence"
    ] == [expected, (180, "parenthetical")]


def test_parenthetical_policy_uses_boundaries_not_surface_punctuation() -> None:
    plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (FlowSegment("The value (x) is fixed.", "en-US", boundary_after=("sentence",)),)
            ),
        ),
    )
    profile = _profile(pauses={"parenthetical": 180, "sentence": 500})

    flow = _group(plan, profile)

    assert [item.text for item in flow if isinstance(item, SpeechItem)] == [
        "The value (x) is fixed."
    ]
    assert [item.reason for item in flow if isinstance(item, PauseItem)] == ["sentence"]


def test_nested_parenthetical_edges_emit_one_pause_per_adjacency() -> None:
    plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment("outer ", "en-US", boundary_after=("parenthetical",)),
                    FlowSegment(
                        "(inside ",
                        "en-US",
                        boundary_before=("parenthetical",),
                        boundary_after=("parenthetical",),
                    ),
                    FlowSegment(
                        "(nested)",
                        "en-US",
                        boundary_before=("parenthetical",),
                        boundary_after=("parenthetical",),
                    ),
                    FlowSegment(
                        " again)",
                        "en-US",
                        boundary_before=("parenthetical",),
                        boundary_after=("parenthetical",),
                    ),
                    FlowSegment(
                        " end.",
                        "en-US",
                        boundary_before=("parenthetical",),
                        boundary_after=("sentence",),
                    ),
                )
            ),
        ),
    )
    profile = _profile(pauses={"parenthetical": 180, "sentence": 500})

    flow = _group(plan, profile)

    assert [item.text for item in flow if isinstance(item, SpeechItem)] == [
        "outer ",
        "(inside ",
        "(nested)",
        " again)",
        " end.",
    ]
    assert [(item.duration_ms, item.reason) for item in flow if isinstance(item, PauseItem)] == [
        (180, "parenthetical"),
        (180, "parenthetical"),
        (180, "parenthetical"),
        (180, "parenthetical"),
        (500, "sentence"),
    ]


def test_clause_and_paragraph_grouping_follow_topology_not_punctuation() -> None:
    plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment("A, ", "en-US", boundary_after=("parenthetical",)),
                    FlowSegment("B. ", "en-US", boundary_after=("clause",)),
                    FlowSegment("C. ", "en-US", boundary_after=("sentence",)),
                    FlowSegment("D. ", "en-US", boundary_after=("paragraph",)),
                    FlowSegment("E.", "en-US"),
                )
            ),
        ),
    )

    clause_flow = _group(plan, _profile(split="clause"))
    assert [item.text for item in clause_flow if isinstance(item, SpeechItem)] == [
        "A, B. ",
        "C. ",
        "D. ",
        "E.",
    ]
    paragraph_flow = _group(plan, _profile(split="paragraph"))
    assert [item.text for item in paragraph_flow if isinstance(item, SpeechItem)] == [
        "A, B. C. D. ",
        "E.",
    ]


def test_role_change_is_hard_boundary_and_role_binding_is_copied() -> None:
    plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment("Hello ", "en-US"),
                    FlowSegment(
                        "there.",
                        "en-US",
                        directives=SegmentDirectives(voice=VoiceDirective(reference="guest")),
                    ),
                )
            ),
        ),
    )
    profile = _profile(
        roles={
            "narrator": RoleProfile(language="en-US", binding={"engine": "a", "voice": 1}),
            "guest": RoleProfile(language="en-GB", binding={"engine": "b", "voice": 2}),
        },
        pauses={"voice_change": 250},
    )

    flow = _group(plan, profile)
    speech = [item for item in flow if isinstance(item, SpeechItem)]
    assert [(item.text, item.role, dict(item.binding)) for item in speech] == [
        ("Hello ", "narrator", {"engine": "a", "voice": 1}),
        ("there.", "guest", {"engine": "b", "voice": 2}),
    ]
    assert speech[0].planning_level == "hard"
    assert speech[0].split_reason == "voice_change"
    assert speech[0].semantic_end == "voice_change"
    assert [(item.duration_ms, item.reason) for item in flow if isinstance(item, PauseItem)] == [
        (250, "voice_change")
    ]


def test_language_change_and_missing_roles_are_hard_failures() -> None:
    language_plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment("Hello ", "en-US"),
                    FlowSegment("bonjour.", "fr-FR"),
                )
            ),
        ),
    )
    language_flow = _group(language_plan, _profile())
    language_speech = [item for item in language_flow if isinstance(item, SpeechItem)]
    assert [item.text for item in language_speech] == ["Hello ", "bonjour."]
    assert language_speech[0].planning_level == "hard"
    assert language_speech[0].split_reason == "directive_change"

    missing_role_plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        "Hello.",
                        "en-US",
                        directives=SegmentDirectives(voice=VoiceDirective(reference="missing")),
                    ),
                )
            ),
        ),
    )
    with pytest.raises(RenderPlanProjectionError, match="role 'missing'") as error:
        _group(missing_role_plan, _profile())
    assert error.value.code == "renderplan.role.missing"
    assert error.value.locator == "f000000.s000"


def test_pause_merge_timed_none_named_and_leading_authored_pause() -> None:
    timed_plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        "One ",
                        "en-US",
                        pause_after=PauseIntent("timed", "180ms"),
                        boundary_after=("sentence",),
                    ),
                    FlowSegment("Two.", "en-US", pause_before=PauseIntent("strong")),
                )
            ),
        ),
    )
    timed_flow = _group(timed_plan, _profile(pauses={"strong": 350, "sentence": 500}))
    assert [
        (item.duration_ms, item.reason) for item in timed_flow if isinstance(item, PauseItem)
    ] == [(180, "timed")]

    none_plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        "One",
                        "en-US",
                        pause_after=PauseIntent("none"),
                        boundary_after=("sentence",),
                    ),
                    FlowSegment("Two.", "en-US"),
                )
            ),
        ),
    )
    none_flow = _group(none_plan, _profile(pauses={"sentence": 500}))
    assert [
        (item.duration_ms, item.reason) for item in none_flow if isinstance(item, PauseItem)
    ] == [(0, "authored_none")]

    named_plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment("One", "en-US", pause_after=PauseIntent("weak")),
                    FlowSegment("Two.", "en-US", pause_before=PauseIntent("strong")),
                )
            ),
        ),
    )
    named_flow = _group(named_plan, _profile(pauses={"weak": 120, "strong": 350}))
    assert [
        (item.duration_ms, item.reason) for item in named_flow if isinstance(item, PauseItem)
    ] == [(350, "strong")]

    leading_plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit((FlowSegment("Ready.", "en-US", pause_before=PauseIntent("timed", "300ms")),)),
        ),
    )
    leading_flow = _group(leading_plan, _profile())
    assert isinstance(leading_flow[0], PauseItem)
    assert (leading_flow[0].duration_ms, leading_flow[0].reason) == (300, "timed")


def test_external_audio_stays_in_source_order_and_empty_audio_source_fails_closed() -> None:
    plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment("before ", "en-US"),
                    FlowSegment(
                        "alternate text",
                        "en-US",
                        directives=SegmentDirectives(
                            audio=AudioDirective(
                                src="bell.wav", clip_begin="10ms", speed="0.8", sound_level="-3dB"
                            )
                        ),
                    ),
                    FlowSegment("after.", "en-US"),
                )
            ),
        ),
    )
    flow = _group(plan, _profile())
    assert [type(item) for item in flow] == [SpeechItem, AudioItem, SpeechItem]
    assert flow[1].src == "bell.wav"
    assert dict(flow[1].options) == {
        "clip_begin": "10ms",
        "speed": "0.8",
        "sound_level": "-3dB",
    }
    assert flow[0].text + flow[2].text == "before after."

    empty_audio = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        "",
                        "en-US",
                        directives=SegmentDirectives(audio=AudioDirective(src="bell.wav")),
                    ),
                )
            ),
        ),
    )
    with pytest.raises(RenderPlanProjectionError) as error:
        _group(empty_audio, _profile())
    assert error.value.code == "renderplan.audio.source_span"


def test_portable_capacity_clause_cut_has_zero_pause_and_token_fallback_is_safe() -> None:
    clause_plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment("first clause ", "en-US", boundary_after=("clause",)),
                    FlowSegment("second clause.", "en-US", boundary_after=("sentence",)),
                )
            ),
        ),
    )
    profile = _profile(
        roles={
            "narrator": RoleProfile(
                language="en-US",
                binding={"engine": "fixture"},
                planner_capacity=CapacityConstraint("characters", 16),
            )
        },
        pauses={"sentence": 500, "clause": 180},
    )
    flow = _group(clause_plan, profile)
    assert [
        (item.text, item.planning_level, item.split_reason)
        for item in flow
        if isinstance(item, SpeechItem)
    ] == [
        ("first clause ", "clause", "capacity"),
        ("second clause.", "clause", "capacity"),
    ]
    assert [(item.duration_ms, item.reason) for item in flow if isinstance(item, PauseItem)] == [
        (0, "capacity"),
        (500, "sentence"),
    ]

    token_plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        "one two three",
                        "en-US",
                        tokens=(TokenView(0, 3), TokenView(4, 7), TokenView(8, 13)),
                        boundary_after=("sentence",),
                    ),
                )
            ),
        ),
    )
    token_profile = _profile(
        roles={
            "narrator": RoleProfile(
                language="en-US",
                binding={"engine": "fixture"},
                planner_capacity=CapacityConstraint("characters", 6),
            )
        },
        fallback=("token",),
    )
    token_flow = _group(token_plan, token_profile)
    token_speech = [item for item in token_flow if isinstance(item, SpeechItem)]
    assert "".join(item.text for item in token_speech) == "one two three"
    assert len(token_speech) > 1
    assert all(item.planning_level == "token" for item in token_speech)
    assert all(
        item.duration_ms == 0 and item.reason == "capacity"
        for item in token_flow
        if isinstance(item, PauseItem) and item.reason == "capacity"
    )


def test_model_token_capacity_is_not_interpreted_by_utterplan() -> None:
    plan = FlowPlan(
        language="en-US",
        flow=(FlowUnit((FlowSegment("No model tokens.", "en-US"),)),),
    )
    profile = _profile(
        roles={
            "narrator": RoleProfile(
                language="en-US",
                binding={"engine": "fixture"},
                planner_capacity=CapacityConstraint("model_tokens", 10),
            )
        }
    )

    with pytest.raises(RenderPlanProjectionError) as error:
        _group(plan, profile)
    assert error.value.code == "renderplan.capacity.metric"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "Because someone called [ART's]{sub=\"A R T's\"} finally.",
            "Because someone called A R T's finally.",
        ),
        (
            'Because someone called [ART’s]{sub="A R T’s"} finally.',
            "Because someone called A R T’s finally.",
        ),
    ],
)
def test_character_spelling_projects_one_sentence_with_exact_request_control(
    source: str, expected: str
) -> None:
    compiled = compile_document(
        source,
        input_format="ssmd",
        config=PlannerConfig(language="en-us", document_format="ssmd"),
    )
    rendered = build_render_plan(compiled.plan, _profile(pauses={"sentence": 120}))
    speech = [item for item in rendered.flow if isinstance(item, SpeechItem)]

    assert len(speech) == 1
    assert speech[0].planning_level == "sentence"
    assert speech[0].text == expected
    tokens = speech[0].tokens
    assert tokens is not None
    t_index = next(
        index for index, (start, end) in enumerate(tokens.span) if speech[0].text[start:end] == "T"
    )
    assert dict(tokens.lemma)[t_index] == "T"
    assert "A- R- T" not in speech[0].text
    assert not any(isinstance(item, PauseItem) for item in rendered.flow)
    say_as = [control for control in speech[0].controls if control.name == "say_as"]
    assert len(say_as) == 1
    control = say_as[0]
    start = expected.index("A R T")
    assert (control.start, control.end) == (start, start + len("A R T"))
    assert dict(control.params) == {"interpret_as": "characters"}
