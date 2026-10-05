import pytest

from utterplan import PauseConfig, PlannerConfig, PlanningError, UtterancePlanner


def test_plain_sentences_paragraphs_and_pauses():
    value = "One sentence. Two sentences.\n\nSecond paragraph."
    plan = UtterancePlanner(PlannerConfig(language="EN_US", document_format="plain")).plan(value)
    assert plan.source.text == value
    assert plan.texts.structural == value
    assert plan.texts.spoken == value
    assert len(plan.segments) == 3
    assert len(plan.units) == 2
    assert plan.segments[0].pause_after.seconds == 0.6
    assert plan.segments[1].pause_after.seconds == 1.0


def test_ssmd_preparation_and_explicit_directives():
    plan = UtterancePlanner(PlannerConfig(language="en-us", document_format="ssmd")).plan(
        '[tomato]{ph="təˈmeɪtoʊ"}'
    )
    assert plan.preparation.backend == "spokenform"
    assert plan.segments[0].directives.pronunciation.phonemes == "təˈmeɪtoʊ"


def test_ssmd_break_marker_and_language():
    plan = UtterancePlanner(PlannerConfig(language="en-us", document_format="ssmd")).plan(
        'Hello ...500ms [Bonjour]{lang="fr"} @mark'
    )
    assert len(plan.segments) >= 2
    assert any(run.language == "fr" for run in plan.languages)
    assert plan.markers[0].name == "mark"
    assert any(segment.pause_after.seconds == 0.5 for segment in plan.segments)


def test_identity_is_deterministic():
    config = PlannerConfig(language="de_DE", text_preparation="identity")
    left = UtterancePlanner(config).plan("Hallo.")
    right = UtterancePlanner(config).plan("Hallo.")
    assert left == right
    assert left.plan_id == right.plan_id


def test_pause_config_default_is_tts():
    assert PauseConfig().mode == "tts"


def test_pass_a_tokens_counts_tokens_not_language_runs():
    plan = UtterancePlanner(
        PlannerConfig(language="en-us", document_format="plain", text_preparation="identity")
    ).plan("One two three.")

    assert plan.document_metadata["planning"]["pass_a_tokens"] == 3
    assert plan.texts.spoken == "One two three."


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            '[outer [inner]{src="inner.wav"} text]{src="outer.wav"}',
            "Overlapping audio annotations",
        ),
        (
            '[]{src="first.wav"}[]{src="second.wav"}',
            "Multiple zero-width audio annotations",
        ),
        (
            '[Audio []{src="point.wav"} fallback]{src="span.wav"}',
            "inside another audio fallback",
        ),
        (
            '[Hello [Bonjour]{lang="fr"} there]{src="multi.wav"}',
            "multiple effective languages",
        ),
        (
            ':::{src="paragraph.wav"}\nFirst.\n\nSecond.\n:::',
            "multiple paragraphs",
        ),
        (
            '[Audio [fallback]{emphasis="strong"} text]{src="nested.wav"}',
            "nested inside an audio fallback",
        ),
    ],
)
def test_unrepresentable_audio_topology_is_rejected(source: str, message: str) -> None:
    planner = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
            text_preparation="identity",
        )
    )

    with pytest.raises(PlanningError, match=message):
        planner.plan(source)


def test_adjacent_audio_annotations_are_distinct_and_supported() -> None:
    planner = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
            text_preparation="identity",
        )
    )
    plan = planner.plan('[first]{src="same.wav"}[second]{src="same.wav"}')
    audio_segments = [segment for segment in plan.segments if segment.directives.audio is not None]

    assert len(audio_segments) == 2
    first_audio = audio_segments[0].directives.audio
    second_audio = audio_segments[1].directives.audio

    assert first_audio is not None
    assert second_audio is not None
    assert first_audio.src == second_audio.src
    assert audio_segments[0].id != audio_segments[1].id
    assert audio_segments[0].spoken_start < audio_segments[1].spoken_start


def test_audio_fallback_is_atomic_across_sentence_segmentation() -> None:
    planner = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
            text_preparation="identity",
        )
    )
    uri = "sfx:impact.knock?seed=42"
    plan = planner.plan(f'[Audio failed. Continue listening.]{{src="{uri}"}}')
    audio_segments = [segment for segment in plan.segments if segment.directives.audio is not None]

    assert len(audio_segments) == 1
    assert audio_segments[0].text == "Audio failed. Continue listening."
    audio = audio_segments[0].directives.audio
    assert audio is not None
    assert audio.src == uri


def test_atomic_audio_fallback_does_not_change_neighboring_speech() -> None:
    planner = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
            text_preparation="identity",
        )
    )
    plan = planner.plan(
        'First sentence.[Audio failed. Continue listening.]{src="sfx:impact.knock"} Last sentence.'
    )
    audio_segments = [segment for segment in plan.segments if segment.directives.audio is not None]
    assert len(audio_segments) == 1
    media = audio_segments[0]

    assert media.text == "Audio failed. Continue listening."
    assert any(
        segment.directives.audio is None and segment.spoken_end <= media.spoken_start
        for segment in plan.segments
    )
    assert any(
        segment.directives.audio is None and segment.spoken_start >= media.spoken_end
        for segment in plan.segments
    )


def test_positive_width_whitespace_fallback_still_gets_one_media_segment() -> None:
    from utterplan.language import LanguageRun
    from utterplan.model import AnnotationSpan
    from utterplan.planner import _apply_atomic_audio_segments

    annotation = AnnotationSpan(
        id="annotation-audio",
        kind="audio",
        attrs={"tag": "audio", "src": "opaque:whitespace"},
        structural_start=0,
        structural_end=3,
        spoken_start=0,
        spoken_end=3,
    )
    segments = _apply_atomic_audio_segments(
        "   ",
        [],
        (LanguageRun("lang-0", 0, 3, "en-us"),),
        (annotation,),
        "en-us",
    )

    assert len(segments) == 1
    assert segments[0].text == "   "
    assert segments[0].spoken_start == 0
    assert segments[0].spoken_end == 3
    assert segments[0].language == "en-us"


def test_zero_width_audio_segment_is_ordered_owned_and_included_in_a_unit() -> None:
    planner = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
            text_preparation="identity",
        )
    )
    uri = "sfx:impact.knock?seed=42"
    plan = planner.plan(f'Before. []{{src="{uri}"}} After.')
    media = next(segment for segment in plan.segments if segment.directives.audio is not None)
    media_index = plan.segments.index(media)
    annotation = next(item for item in plan.annotations if item.attrs.get("src") == uri)

    assert media.text == ""
    assert media.spoken_start == media.spoken_end
    assert media.token_indices == ()
    assert annotation.id in media.annotation_ids
    assert media.directives.audio is not None and media.directives.audio.src == uri
    assert media_index > 0 and media_index < len(plan.segments) - 1
    assert plan.segments[media_index - 1].spoken_end == media.spoken_start
    assert plan.segments[media_index + 1].spoken_start >= media.spoken_start
    assert media.sentence == plan.segments[media_index - 1].sentence
    assert [segment.id for segment in plan.segments] == [
        f"seg-{index:06d}" for index in range(len(plan.segments))
    ]
    assert any(media.id in unit.segment_ids for unit in plan.units)
    assert media.text == plan.texts.spoken[media.spoken_start : media.spoken_end]

    plan.validate()


def test_media_only_document_uses_declared_language_and_round_trips() -> None:
    source = (
        '---\nssmd_version: "0.9"\nlanguage: en-US\n---\n'
        '[]{src="sfx:door.open?seed=42" desc="Door opening"}'
    )
    planner = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
            text_preparation="identity",
        )
    )
    plan = planner.plan(source)

    assert plan.texts.spoken == ""
    assert plan.languages == ()
    assert len(plan.segments) == 1
    assert plan.segments[0].text == ""
    assert plan.segments[0].language == "en-US"
    assert plan.segments[0].token_indices == ()
    assert plan.segments[0].directives.audio is not None
    assert len(plan.units) == 1
    plan.validate()
    assert type(plan).from_json(plan.to_json()) == plan


def test_point_audio_at_document_start_uses_following_language_context() -> None:
    planner = UtterancePlanner(
        PlannerConfig(
            language="en-us",
            document_format="ssmd",
            text_preparation="identity",
        )
    )
    plan = planner.plan('[]{src="clip.wav"}[Bonjour.]{lang="fr"}')
    media = next(segment for segment in plan.segments if segment.directives.audio is not None)

    assert media.language == "fr"
    assert media.spoken_start == media.spoken_end == 0
    media_index = plan.segments.index(media)
    assert media_index == 0
    assert plan.segments[media_index + 1].spoken_start == media.spoken_start
