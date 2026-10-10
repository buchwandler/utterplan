from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from utterplan.segmentation import propose_phrasplit_sentence_boundaries


def _proposal(text: str, start: Any, end: Any, *, surface: Any = None) -> SimpleNamespace:
    return SimpleNamespace(
        char_start=start,
        char_end=end,
        text=text[start:end]
        if surface is None and type(start) is int and type(end) is int
        else surface,
        paragraph_idx=999,
        sentence_idx=999,
        clause_idx=999,
    )


def _phrasplit(
    monkeypatch: pytest.MonkeyPatch, result: Any = None, *, error: Exception | None = None
):
    calls: list[tuple[str, dict[str, Any]]] = []

    def split_with_offsets(text: str, **kwargs: Any) -> Any:
        calls.append((text, kwargs))
        if error is not None:
            raise error
        return result

    monkeypatch.setitem(
        sys.modules,
        "phrasplit",
        SimpleNamespace(split_with_offsets=split_with_offsets),
    )
    return calls


def test_adapter_validates_spans_and_allows_only_whitespace_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "  Hello. \tWorld!  "
    proposals = [_proposal(text, 2, 8), _proposal(text, 10, 16)]
    calls = _phrasplit(monkeypatch, proposals)

    batch = propose_phrasplit_sentence_boundaries(
        text,
        language="en-US",
        run_start=100,
        run_id="language-0007",
    )

    assert not batch.degraded
    assert batch.repairs == ()
    assert [candidate.position for candidate in batch.candidates] == [108]
    assert batch.candidates[0].origin == "phrasplit"
    assert batch.candidates[0].language_run_id == "language-0007"
    assert calls == [(text, {"mode": "sentence", "use_spacy": False, "language": "en-us"})]


def test_adapter_does_not_promote_language_run_endpoint_to_sentence_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "Hello bonjour"
    _phrasplit(monkeypatch, [_proposal(text, 0, len(text))])

    batch = propose_phrasplit_sentence_boundaries(
        text,
        language="en",
        run_start=0,
        run_id="run-1",
    )

    assert batch.candidates == ()
    assert not batch.degraded


@pytest.mark.parametrize(
    "result",
    (
        None,
        17,
        [_proposal("abc", True, 2)],
        [_proposal("abc", 0, "2")],
        [_proposal("abc", 0, 1.5)],
        [_proposal("abc", -1, 2)],
        [_proposal("abc", 0, 4)],
        [_proposal("abc", 1, 1)],
        [_proposal("abc", 2, 1)],
        [_proposal("abc", 0, 2, surface="xy")],
        [_proposal("abc", 0, 2), _proposal("abc", 1, 3)],
        [_proposal("abc", 1, 3), _proposal("abc", 0, 1)],
        [_proposal("abc", 0, 1), _proposal("abc", 0, 1)],
    ),
)
def test_adapter_discards_entire_malformed_batch(
    monkeypatch: pytest.MonkeyPatch, result: Any
) -> None:
    _phrasplit(monkeypatch, result)

    batch = propose_phrasplit_sentence_boundaries(
        "abc",
        language="en",
        run_start=20,
        run_id="run-1",
    )

    assert batch.degraded
    assert batch.candidates == ()
    assert len(batch.repairs) == 1
    assert batch.repairs[0].code in {
        "segmentation.phrasplit_failed",
        "segmentation.phrasplit_invalid",
    }


@pytest.mark.parametrize(
    ("text", "spans"),
    (
        ("xabc", [(1, 4)]),
        ("abcx", [(0, 3)]),
        ("abxc", [(0, 2), (3, 4)]),
        ("a,b", [(0, 1), (2, 3)]),
    ),
)
def test_adapter_rejects_non_whitespace_omissions(
    monkeypatch: pytest.MonkeyPatch, text: str, spans: list[tuple[int, int]]
) -> None:
    _phrasplit(monkeypatch, [_proposal(text, start, end) for start, end in spans])

    batch = propose_phrasplit_sentence_boundaries(
        text,
        language="en",
        run_start=5,
        run_id="run-1",
    )

    assert batch.degraded
    assert batch.repairs[0].code == "segmentation.phrasplit_invalid"
    assert "uncovered non-whitespace" in batch.repairs[0].message


@pytest.mark.parametrize(
    "error", (TypeError("bad call"), ValueError("bad call"), RuntimeError("bad call"))
)
def test_adapter_recovers_from_dependency_call_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    _phrasplit(monkeypatch, error=error)

    batch = propose_phrasplit_sentence_boundaries(
        "valid prose.",
        language="en",
        run_start=0,
        run_id="run-1",
    )

    assert batch.degraded
    assert batch.candidates == ()
    assert batch.repairs[0].code == "segmentation.phrasplit_failed"


def test_adapter_recovers_when_dependency_iterator_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_iterator():
        yield _proposal("abc", 0, 1)
        raise RuntimeError("broken iterator")

    _phrasplit(monkeypatch, broken_iterator())

    batch = propose_phrasplit_sentence_boundaries(
        "abc",
        language="en",
        run_start=0,
        run_id="run-1",
    )

    assert batch.degraded
    assert batch.candidates == ()
    assert batch.repairs[0].code == "segmentation.phrasplit_failed"


def test_empty_text_and_empty_proposals_are_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _phrasplit(monkeypatch, [])

    batch = propose_phrasplit_sentence_boundaries(
        "",
        language="en",
        run_start=0,
        run_id="run-1",
    )

    assert batch.candidates == ()
    assert batch.repairs == ()
    assert not batch.degraded
