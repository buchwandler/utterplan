from __future__ import annotations

import re
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


@pytest.mark.parametrize("field_name", ("lemma", "morph"))
@pytest.mark.parametrize("blank", (None, "", " ", "\t", "\n", "\u00a0", "\u2007", "\u202f"))
def test_optional_blank_sparse_token_values_are_omitted(field_name: str, blank: str | None) -> None:
    blank_value = {field_name: blank}
    plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        "x y z",
                        "en-US",
                        tokens=(
                            TokenView(0, 1, lemma="x", morph="Number=Sing"),
                            TokenView(2, 3, **blank_value),
                            TokenView(4, 5, lemma="z", morph="Tense=Past"),
                        ),
                    ),
                )
            ),
        ),
    )
    bundle = build_source_index(plan).tokens_for((SourceSpan("f000000.s000", 0, 5),))

    assert bundle is not None
    assert getattr(bundle, field_name) == (
        (0, "x" if field_name == "lemma" else "Number=Sing"),
        (2, "z" if field_name == "lemma" else "Tense=Past"),
    )


@pytest.mark.parametrize("field_name", ("lemma", "morph"))
def test_required_blank_sparse_token_value_fails_with_source_location(field_name: str) -> None:
    plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        "x y z",
                        "en-US",
                        tokens=(
                            TokenView(0, 1, **{field_name: "x"}),
                            TokenView(2, 3, **{field_name: "\u00a0"}),
                            TokenView(4, 5, **{field_name: "z"}),
                        ),
                    ),
                )
            ),
        ),
    )
    index = build_source_index(plan)

    with pytest.raises(
        RenderPlanProjectionError, match=f"required token field '{field_name}' is unavailable"
    ) as error:
        index.tokens_for((SourceSpan("f000000.s000", 0, 5),), required_fields=(field_name,))

    assert error.value.code == "renderplan.token.required"
    assert error.value.locator == "f000000.s000"
    assert error.value.token_index == 1


@pytest.mark.parametrize(
    "lemma", ("be", "I", "T", "armoredHostile1", "ß", " leading ", "trailing ")
)
def test_nonblank_sparse_lemma_is_preserved_exactly(lemma: str) -> None:
    plan = FlowPlan(
        language="en-US",
        flow=(FlowUnit((FlowSegment("x", "en-US", tokens=(TokenView(0, 1, lemma=lemma),)),)),),
    )

    bundle = build_source_index(plan).tokens_for((SourceSpan("f000000.s000", 0, 1),))

    assert bundle is not None
    assert bundle.lemma == ((0, lemma),)


def test_partial_dense_pos_and_tag_columns_are_omitted_without_padding() -> None:
    plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        "one two",
                        "en-US",
                        tokens=(
                            TokenView(0, 3, pos="DET", tag="DT"),
                            TokenView(4, 7, pos=None, tag=" \u00a0"),
                        ),
                    ),
                )
            ),
        ),
    )
    index = build_source_index(plan)
    source = (SourceSpan("f000000.s000", 0, 7),)

    bundle = index.tokens_for(source)

    assert bundle is not None
    assert bundle.pos == ()
    assert bundle.tag == ()
    for field_name in ("pos", "tag"):
        with pytest.raises(
            RenderPlanProjectionError,
            match=f"required token field '{field_name}' is unavailable",
        ) as error:
            index.tokens_for(source, required_fields=(field_name,))
        assert error.value.code == "renderplan.token.required"
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


_TOKEN_PATTERN = re.compile(r"[^\W_]+(?:['’][^\W_]+)*|[()\[\]{}.,;:!?]", re.UNICODE)


def _token_views(
    text: str, *, include_pos: bool = True, bracket_metadata: bool = True
) -> tuple[TokenView, ...]:
    tokens: list[TokenView] = []
    for match in _TOKEN_PATTERN.finditer(text):
        surface = match.group()
        is_word = bool(re.fullmatch(r"[^\W_]+(?:['’][^\W_]+)*", surface, re.UNICODE))
        is_open = surface in {"(", "[", "{"}
        is_close = surface in {")", "]", "}"}
        tokens.append(
            TokenView(
                match.start(),
                match.end(),
                lemma=surface.casefold() if is_word else None,
                pos=("NOUN" if is_word else "PUNCT") if include_pos else None,
                tag=("NN" if is_word else "-LRB-" if is_open else "-RRB-" if is_close else surface)
                if include_pos or (bracket_metadata and (is_open or is_close))
                else None,
                morph=("PunctSide=Ini" if is_open else "PunctSide=Fin" if is_close else None)
                if bracket_metadata
                else None,
            )
        )
    return tuple(tokens)


def _parenthetical_plan(
    *,
    entry_pause: PauseIntent | None = None,
    exit_pause: PauseIntent | None = None,
) -> FlowPlan:
    host = "Before "
    aside = "(aside)"
    continuation = " after."
    return FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        host,
                        "en-US",
                        tokens=_token_views(host),
                        pause_after=entry_pause,
                        boundary_after=("parenthetical",),
                    ),
                    FlowSegment(
                        aside,
                        "en-US",
                        directives=SegmentDirectives(emphasis=EmphasisDirective("strong")),
                        tokens=_token_views(aside),
                        pause_after=exit_pause,
                        boundary_before=("parenthetical",),
                        boundary_after=("parenthetical",),
                    ),
                    FlowSegment(
                        continuation,
                        "en-US",
                        tokens=_token_views(continuation),
                        boundary_before=("parenthetical",),
                        boundary_after=("sentence",),
                    ),
                )
            ),
        ),
    )


def _inline_parenthetical_plan(
    host: str,
    aside: str,
    continuation: str,
    *,
    entry_pause: PauseIntent | None = None,
    exit_pause: PauseIntent | None = None,
    include_pos: bool = True,
    bracket_metadata: bool = True,
) -> FlowPlan:
    return FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        host,
                        "en-US",
                        tokens=_token_views(
                            host, include_pos=include_pos, bracket_metadata=bracket_metadata
                        ),
                        pause_after=entry_pause,
                        boundary_after=("parenthetical",),
                    ),
                    FlowSegment(
                        aside,
                        "en-US",
                        tokens=_token_views(
                            aside, include_pos=include_pos, bracket_metadata=bracket_metadata
                        ),
                        pause_after=exit_pause,
                        boundary_before=("parenthetical",),
                        boundary_after=("parenthetical",),
                    ),
                    FlowSegment(
                        continuation,
                        "en-US",
                        tokens=_token_views(
                            continuation, include_pos=include_pos, bracket_metadata=bracket_metadata
                        ),
                        boundary_before=("parenthetical",),
                        boundary_after=("sentence",),
                    ),
                )
            ),
        ),
    )


def _target_parenthetical_plan() -> FlowPlan:
    segments = (
        "The cameras spotted more human activity on a platform two levels above us, ",
        "a scramble of workers ",
        "(probably the real workers)",
        " trying to get to a lift tube and a few workers ",
        "(the security humans pretending to be workers)",
        " holding them back.",
    )
    return FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        segments[0],
                        "en-US",
                        tokens=_token_views(segments[0]),
                        boundary_after=("clause",),
                    ),
                    FlowSegment(segments[1], "en-US", tokens=_token_views(segments[1])),
                    FlowSegment(
                        segments[2],
                        "en-US",
                        directives=SegmentDirectives(emphasis=EmphasisDirective("strong")),
                        tokens=_token_views(segments[2]),
                        boundary_before=("parenthetical",),
                    ),
                    FlowSegment(
                        segments[3],
                        "en-US",
                        tokens=_token_views(segments[3]),
                        boundary_before=("parenthetical",),
                    ),
                    FlowSegment(
                        segments[4],
                        "en-US",
                        directives=SegmentDirectives(emphasis=EmphasisDirective("strong")),
                        tokens=_token_views(segments[4]),
                        boundary_before=("parenthetical",),
                    ),
                    FlowSegment(
                        segments[5],
                        "en-US",
                        tokens=_token_views(segments[5]),
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
def test_short_parenthetical_edges_remain_joined_and_preserve_request_fidelity(
    duration: int,
) -> None:
    plan = _parenthetical_plan()
    profile = _profile(pauses={"parenthetical": duration, "sentence": 500})

    flow = _group(plan, profile)
    speech = [item for item in flow if isinstance(item, SpeechItem)]
    pauses = [item for item in flow if isinstance(item, PauseItem)]

    assert [item.text for item in speech] == ["Before (aside) after."]
    assert [item.semantic_end for item in speech] == ["sentence"]
    assert [(item.duration_ms, item.reason) for item in pauses] == [(500, "sentence")]
    assert speech[0].source == (
        SourceSpan("f000000.s000", 0, 7),
        SourceSpan("f000000.s001", 0, 7),
        SourceSpan("f000000.s002", 0, 7),
    )
    assert speech[0].text == build_source_index(plan).text_for(speech[0].source)
    assert all(
        0 <= start < end <= len(speech[0].text)
        for start, end in speech[0].tokens.span  # type: ignore[union-attr]
    )
    assert [(control.start, control.end, control.name) for control in speech[0].controls] == [
        (7, 14, "emphasis")
    ]
    assert _group(plan, profile) == flow


def test_exact_problem_sentence_keeps_both_host_continuations_in_request() -> None:
    plan = _target_parenthetical_plan()
    profile = _profile(pauses={"parenthetical": 180, "sentence": 500})

    flow = _group(plan, profile)
    render_plan = build_render_plan(plan, profile)
    render_plan.validate_against_profile(profile)
    assert render_plan.flow == flow
    speech = [item for item in flow if isinstance(item, SpeechItem)]
    pauses = [item for item in flow if isinstance(item, PauseItem)]
    expected = [
        "The cameras spotted more human activity on a platform two levels above us, "
        "a scramble of workers ",
        "(probably the real workers) trying to get to a lift tube and a few workers ",
        "(the security humans pretending to be workers) holding them back.",
    ]

    assert [item.text for item in speech] == expected
    assert len(speech) == 3
    assert [item.semantic_end for item in speech] == [
        "parenthetical",
        "parenthetical",
        "sentence",
    ]
    assert [(item.duration_ms, item.reason) for item in pauses] == [
        (180, "parenthetical"),
        (180, "parenthetical"),
        (500, "sentence"),
    ]
    assert not any(item.text.startswith(" trying") for item in speech)
    assert not any(item.text.startswith(" holding them back") for item in speech)
    index = build_source_index(plan)
    assert all(item.text == index.text_for(item.source) for item in speech)
    assert all(
        item.tokens is not None
        and all(0 <= start < end <= len(item.text) for start, end in item.tokens.span)
        for item in speech
    )
    assert [
        [(control.start, control.end, control.name) for control in item.controls] for item in speech
    ] == [
        [],
        [(0, len("(probably the real workers)"), "emphasis")],
        [(0, len("(the security humans pretending to be workers)"), "emphasis")],
    ]


@pytest.mark.parametrize("aside", ("(art)", "(surprise)", "(one)", "(two)"))
def test_short_inline_asides_are_not_automatically_isolated(aside: str) -> None:
    plan = _inline_parenthetical_plan(
        "Because this person really did ", aside, " think the intel was wrong."
    )
    flow = _group(plan, _profile(pauses={"parenthetical": 180, "sentence": 500}))

    assert [item.text for item in flow if isinstance(item, SpeechItem)] == [
        f"Because this person really did {aside} think the intel was wrong."
    ]
    assert [item.reason for item in flow if isinstance(item, PauseItem)] == ["sentence"]


def test_short_host_does_not_trigger_substantial_aside_split() -> None:
    plan = _inline_parenthetical_plan("I ", "(probably the real worker)", " will finish the job.")
    flow = _group(plan, _profile(pauses={"parenthetical": 180, "sentence": 500}))

    assert [item.text for item in flow if isinstance(item, SpeechItem)] == [
        "I (probably the real worker) will finish the job."
    ]
    assert [item.reason for item in flow if isinstance(item, PauseItem)] == ["sentence"]


def test_substantial_open_edge_splits_once_and_close_edge_joins_continuation() -> None:
    plan = _inline_parenthetical_plan(
        "The host group has enough words ",
        "(this aside has enough words)",
        " continues the sentence.",
    )
    flow = _group(plan, _profile(pauses={"parenthetical": 180, "sentence": 500}))
    speech = [item for item in flow if isinstance(item, SpeechItem)]

    assert [item.text for item in speech] == [
        "The host group has enough words ",
        "(this aside has enough words) continues the sentence.",
    ]
    assert [item.reason for item in flow if isinstance(item, PauseItem)] == [
        "parenthetical",
        "sentence",
    ]


def test_lexical_count_fallback_uses_token_surfaces_without_pos() -> None:
    plan = _inline_parenthetical_plan(
        "A host group contains enough words ",
        "(this aside has enough words)",
        " continues the sentence.",
        include_pos=False,
        bracket_metadata=False,
    )
    flow = _group(plan, _profile(pauses={"parenthetical": 180, "sentence": 500}))

    assert [item.text for item in flow if isinstance(item, SpeechItem)] == [
        "A host group contains enough words ",
        "(this aside has enough words) continues the sentence.",
    ]


def test_ambiguous_parenthetical_orientation_is_not_split_automatically() -> None:
    plan = _inline_parenthetical_plan(
        "The host group has enough words ",
        "this aside has enough words",
        " continues the sentence.",
    )
    flow = _group(plan, _profile(pauses={"parenthetical": 180, "sentence": 500}))

    assert [item.text for item in flow if isinstance(item, SpeechItem)] == [
        "The host group has enough words this aside has enough words continues the sentence."
    ]
    assert [item.reason for item in flow if isinstance(item, PauseItem)] == ["sentence"]


def test_adjacent_parenthetical_open_wins_over_previous_close() -> None:
    plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        "The initial host has enough words ",
                        "en-US",
                        tokens=_token_views("The initial host has enough words "),
                        boundary_after=("parenthetical",),
                    ),
                    FlowSegment(
                        "(alpha beta gamma delta)",
                        "en-US",
                        tokens=_token_views("(alpha beta gamma delta)"),
                        boundary_before=("parenthetical",),
                        boundary_after=("parenthetical",),
                    ),
                    FlowSegment(
                        "(epsilon zeta eta theta)",
                        "en-US",
                        tokens=_token_views("(epsilon zeta eta theta)"),
                        boundary_before=("parenthetical",),
                        boundary_after=("parenthetical",),
                    ),
                    FlowSegment(
                        " continues the sentence.",
                        "en-US",
                        tokens=_token_views(" continues the sentence."),
                        boundary_before=("parenthetical",),
                        boundary_after=("sentence",),
                    ),
                )
            ),
        ),
    )
    flow = _group(plan, _profile(pauses={"parenthetical": 180, "sentence": 500}))

    assert [item.text for item in flow if isinstance(item, SpeechItem)] == [
        "The initial host has enough words ",
        "(alpha beta gamma delta)",
        "(epsilon zeta eta theta) continues the sentence.",
    ]
    assert [item.reason for item in flow if isinstance(item, PauseItem)] == [
        "parenthetical",
        "parenthetical",
        "sentence",
    ]


def test_parenthetical_policy_is_disabled_by_none_mode() -> None:
    plan = _inline_parenthetical_plan(
        "The host group has enough words ",
        "(this aside has enough words)",
        " continues the sentence.",
    )
    profile = replace(
        _profile(pauses={"parenthetical": 180, "sentence": 500}),
        pauses=PausePolicy(mode="none", durations_ms={"parenthetical": 180, "sentence": 500}),
        profile_id=None,
    )

    flow = _group(plan, profile)

    assert [item.text for item in flow if isinstance(item, SpeechItem)] == [
        "The host group has enough words (this aside has enough words) continues the sentence."
    ]
    assert not any(isinstance(item, PauseItem) and item.reason == "parenthetical" for item in flow)


def test_authored_none_suppresses_eligible_automatic_open_split() -> None:
    plan = _inline_parenthetical_plan(
        "The host group has enough words ",
        "(this aside has enough words)",
        " continues the sentence.",
        entry_pause=PauseIntent("none"),
    )
    flow = _group(plan, _profile(pauses={"parenthetical": 180, "sentence": 500}))

    assert [item.text for item in flow if isinstance(item, SpeechItem)] == [
        "The host group has enough words (this aside has enough words) continues the sentence."
    ]
    assert [item.reason for item in flow if isinstance(item, PauseItem)] == ["sentence"]


def test_authored_breaks_still_split_parenthetical_entry_or_close() -> None:
    plan = _inline_parenthetical_plan(
        "The host group has enough words ",
        "(this aside has enough words)",
        " continues the sentence.",
        exit_pause=PauseIntent("timed", "350ms"),
    )
    flow = _group(plan, _profile(pauses={"parenthetical": 180, "sentence": 500}))

    assert [item.text for item in flow if isinstance(item, SpeechItem)] == [
        "The host group has enough words ",
        "(this aside has enough words)",
        " continues the sentence.",
    ]
    assert [(item.duration_ms, item.reason) for item in flow if isinstance(item, PauseItem)] == [
        (180, "parenthetical"),
        (350, "timed"),
        (500, "sentence"),
    ]


def test_authored_timed_pause_on_close_splits_despite_automatic_close_suppression() -> None:
    plan = _inline_parenthetical_plan(
        "The host group has enough words ",
        "(this aside has enough words)",
        " continues the sentence.",
        exit_pause=PauseIntent("strong"),
    )
    flow = _group(
        plan,
        _profile(pauses={"parenthetical": 180, "sentence": 500, "strong": 420}),
    )

    assert [item.text for item in flow if isinstance(item, SpeechItem)] == [
        "The host group has enough words ",
        "(this aside has enough words)",
        " continues the sentence.",
    ]
    assert [(item.duration_ms, item.reason) for item in flow if isinstance(item, PauseItem)] == [
        (180, "parenthetical"),
        (420, "strong"),
        (500, "sentence"),
    ]


def test_parenthetical_zero_duration_still_splits_eligible_open_edge() -> None:
    plan = _inline_parenthetical_plan(
        "The host group has enough words ",
        "(this aside has enough words)",
        " continues the sentence.",
    )
    flow = _group(plan, _profile(pauses={"parenthetical": 0, "sentence": 500}))

    assert [item.text for item in flow if isinstance(item, SpeechItem)] == [
        "The host group has enough words ",
        "(this aside has enough words) continues the sentence.",
    ]
    assert [(item.duration_ms, item.reason) for item in flow if isinstance(item, PauseItem)] == [
        (0, "parenthetical"),
        (500, "sentence"),
    ]


def test_authored_timed_pause_on_eligible_open_keeps_exact_duration() -> None:
    plan = _inline_parenthetical_plan(
        "The host group has enough words ",
        "(this aside has enough words)",
        " continues the sentence.",
        entry_pause=PauseIntent("timed", "350ms"),
    )
    flow = _group(plan, _profile(pauses={"parenthetical": 180, "sentence": 500}))

    assert [item.text for item in flow if isinstance(item, SpeechItem)] == [
        "The host group has enough words ",
        "(this aside has enough words) continues the sentence.",
    ]
    assert [(item.duration_ms, item.reason) for item in flow if isinstance(item, PauseItem)] == [
        (350, "timed"),
        (500, "sentence"),
    ]


def test_coincident_paragraph_and_parenthetical_edge_resolves_once() -> None:
    edge = ("paragraph", "parenthetical")
    plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        "The host group has enough words ",
                        "en-US",
                        tokens=_token_views("The host group has enough words "),
                        boundary_after=edge,
                    ),
                    FlowSegment(
                        "(this aside has enough words)",
                        "en-US",
                        tokens=_token_views("(this aside has enough words)"),
                        boundary_before=edge,
                    ),
                )
            ),
        ),
    )
    flow = _group(plan, _profile(pauses={"paragraph": 800, "parenthetical": 180}))

    assert [item.text for item in flow if isinstance(item, SpeechItem)] == [
        "The host group has enough words ",
        "(this aside has enough words)",
    ]
    assert [item.semantic_end for item in flow if isinstance(item, SpeechItem)] == [
        "paragraph",
        "none",
    ]
    assert [(item.duration_ms, item.reason) for item in flow if isinstance(item, PauseItem)] == [
        (800, "paragraph")
    ]


def test_voice_change_owns_coincident_parenthetical_entry_boundary() -> None:
    host = "The host group has enough words "
    aside = "(this aside has enough words)"
    continuation = " continues the sentence."
    plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        host,
                        "en-US",
                        tokens=_token_views(host),
                        boundary_after=("parenthetical",),
                    ),
                    FlowSegment(
                        aside,
                        "en-US",
                        directives=SegmentDirectives(voice=VoiceDirective(reference="guest")),
                        tokens=_token_views(aside),
                        boundary_before=("parenthetical",),
                        boundary_after=("parenthetical",),
                    ),
                    FlowSegment(
                        continuation,
                        "en-US",
                        directives=SegmentDirectives(voice=VoiceDirective(reference="guest")),
                        tokens=_token_views(continuation),
                        boundary_before=("parenthetical",),
                        boundary_after=("sentence",),
                    ),
                )
            ),
        ),
    )
    profile = _profile(
        roles={
            "narrator": RoleProfile(language="en-US", binding={"engine": "fixture"}),
            "guest": RoleProfile(language="en-US", binding={"engine": "guest"}),
        },
        pauses={"parenthetical": 180, "voice_change": 260, "sentence": 500},
    )
    flow = _group(plan, profile)

    assert [item.text for item in flow if isinstance(item, SpeechItem)] == [
        host,
        aside + continuation,
    ]
    assert [item.semantic_end for item in flow if isinstance(item, SpeechItem)] == [
        "voice_change",
        "sentence",
    ]
    assert [item.reason for item in flow if isinstance(item, PauseItem)] == [
        "voice_change",
        "sentence",
    ]


def test_authored_none_resolves_coincident_sentence_parenthetical_edge_once() -> None:
    edge = ("sentence", "parenthetical")
    plan = FlowPlan(
        language="en-US",
        flow=(
            FlowUnit(
                (
                    FlowSegment(
                        "The host group has enough words ",
                        "en-US",
                        tokens=_token_views("The host group has enough words "),
                        pause_after=PauseIntent("none"),
                        boundary_after=edge,
                    ),
                    FlowSegment(
                        "(this aside has enough words)",
                        "en-US",
                        tokens=_token_views("(this aside has enough words)"),
                        boundary_before=edge,
                    ),
                )
            ),
        ),
    )
    flow = _group(plan, _profile(pauses={"parenthetical": 180, "sentence": 500}))
    speech = [item for item in flow if isinstance(item, SpeechItem)]
    pauses = [item for item in flow if isinstance(item, PauseItem)]

    assert [item.text for item in speech] == [
        "The host group has enough words ",
        "(this aside has enough words)",
    ]
    assert speech[0].semantic_end == "sentence"
    assert [(item.duration_ms, item.reason) for item in pauses] == [(0, "authored_none")]


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


def test_nested_parenthetical_edges_do_not_force_symmetric_splits() -> None:
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
    flow = _group(plan, _profile(pauses={"parenthetical": 180, "sentence": 500}))

    assert [item.text for item in flow if isinstance(item, SpeechItem)] == [
        "outer (inside (nested) again) end."
    ]
    assert [item.reason for item in flow if isinstance(item, PauseItem)] == ["sentence"]


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
