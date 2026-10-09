from __future__ import annotations

import json
from pathlib import Path

import pytest

from utterplan.ssmdbook import (
    SSMDBookError,
    load_ssmdbook_index,
    resolve_ssmdbook_root,
    select_ssmdbook_chapters,
    selected_chapter_path,
)


def _entry(
    number: int, *, chapter_id: str | None = None, path: str | None = None
) -> dict[str, object]:
    return {
        "id": chapter_id or f"chapter-{number:04d}",
        "source_number": number,
        "path": path or f"chapters/chapter-{number:04d}.ssmd.md",
        "title": f"Chapter {number}",
        "sha256": f"{number:064x}",
    }


def _manifest(chapters: list[object]) -> dict[str, object]:
    return {
        "format": "ssmdconvert.book",
        "schema_version": 1,
        "ssmd_version": "0.9",
        "chapters": chapters,
    }


def _write_manifest(root: Path, value: object) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "manifest.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _book(tmp_path: Path, numbers: tuple[int, ...] = (5, 7, 6)) -> Path:
    root = tmp_path / "Example.ssmdbook"
    (root / "chapters").mkdir(parents=True)
    _write_manifest(root, _manifest([_entry(number) for number in numbers]))
    return root


def test_resolves_manifest_root_and_canonical_chapters_directory(tmp_path: Path) -> None:
    root = _book(tmp_path)

    assert resolve_ssmdbook_root(root) == root.resolve()
    assert resolve_ssmdbook_root(root / "chapters") == root.resolve()
    assert load_ssmdbook_index(root / "chapters").root == root.resolve()


def test_root_detection_uses_manifest_not_suffix(tmp_path: Path) -> None:
    root = tmp_path / "book-without-extension"
    (root / "chapters").mkdir(parents=True)
    _write_manifest(root, _manifest([]))

    assert resolve_ssmdbook_root(root) == root.resolve()


def test_unrecognized_input_reports_expected_manifest_location(tmp_path: Path) -> None:
    with pytest.raises(SSMDBookError, match="expected manifest.json"):
        resolve_ssmdbook_root(tmp_path / "chapters")


def test_index_preserves_manifest_order_and_digest_without_reading_chapters(tmp_path: Path) -> None:
    root = _book(tmp_path, (5, 7, 6))
    # Chapter sources may be missing or malformed until selected for compilation.
    index = load_ssmdbook_index(root)

    assert [chapter.source_number for chapter in index.chapters] == [5, 7, 6]
    assert index.chapters[0].expected_sha256 == f"{5:064x}"
    assert selected_chapter_path(index, index.chapters[0]) == root / "chapters/chapter-0005.ssmd.md"


def test_selector_all_and_none_select_every_chapter_in_manifest_order(tmp_path: Path) -> None:
    index = load_ssmdbook_index(_book(tmp_path))

    assert select_ssmdbook_chapters(index, None) == index.chapters
    assert select_ssmdbook_chapters(index, "all") == index.chapters


def test_selector_ranges_use_source_numbers_and_preserve_manifest_order(tmp_path: Path) -> None:
    index = load_ssmdbook_index(_book(tmp_path, (5, 7, 6, 1, 3, 4, 9)))

    assert [chapter.source_number for chapter in select_ssmdbook_chapters(index, "5-7")] == [
        5,
        7,
        6,
    ]
    assert [chapter.source_number for chapter in select_ssmdbook_chapters(index, "1, 3-5, 9")] == [
        5,
        1,
        3,
        4,
        9,
    ]


def test_duplicate_selector_numbers_do_not_duplicate_work(tmp_path: Path) -> None:
    index = load_ssmdbook_index(_book(tmp_path, (5, 6, 7)))

    assert [chapter.source_number for chapter in select_ssmdbook_chapters(index, "5,5,5-7")] == [
        5,
        6,
        7,
    ]


@pytest.mark.parametrize(
    "selector",
    ["", "  ", "5-", "-5", "5--7", "1,,2", "0", "-1", "1,abc", "17-5"],
)
def test_rejects_empty_malformed_nonpositive_and_reversed_selectors(
    tmp_path: Path, selector: str
) -> None:
    index = load_ssmdbook_index(_book(tmp_path, (1, 2, 5, 17)))

    with pytest.raises(SSMDBookError):
        select_ssmdbook_chapters(index, selector)


def test_selector_rejects_missing_source_numbers(tmp_path: Path) -> None:
    index = load_ssmdbook_index(_book(tmp_path, (5, 7)))

    with pytest.raises(SSMDBookError, match="missing source number.*6"):
        select_ssmdbook_chapters(index, "5-7")


def test_large_missing_range_is_rejected_without_expanding_every_number(tmp_path: Path) -> None:
    index = load_ssmdbook_index(_book(tmp_path, (1, 2)))

    with pytest.raises(SSMDBookError, match="missing source number.*3"):
        select_ssmdbook_chapters(index, "1-999999999999999999999999999999999999999")


def test_extremely_long_selector_integer_is_a_usage_error(tmp_path: Path) -> None:
    index = load_ssmdbook_index(_book(tmp_path, (1,)))

    with pytest.raises(SSMDBookError, match="malformed chapter selector"):
        select_ssmdbook_chapters(index, "9" * 5000)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("format", "future.book", "unsupported ssmdbook format"),
        ("schema_version", 2, "unsupported ssmdbook schema_version"),
        ("schema_version", True, "unsupported ssmdbook schema_version"),
        ("ssmd_version", "1.0", "unsupported ssmdbook ssmd_version"),
        ("chapters", {}, "chapters must be an array"),
    ],
)
def test_rejects_unsupported_manifest_header(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    root = tmp_path / "book.ssmdbook"
    data = _manifest([])
    data[field] = value
    _write_manifest(root, data)

    with pytest.raises(SSMDBookError, match=message):
        load_ssmdbook_index(root)


def test_rejects_non_object_root_and_nonstandard_json_constants(tmp_path: Path) -> None:
    root = tmp_path / "book.ssmdbook"
    manifest = _write_manifest(root, [])
    with pytest.raises(SSMDBookError, match="root must be a JSON object"):
        load_ssmdbook_index(root)

    manifest.write_text('{"value": NaN}', encoding="utf-8")
    with pytest.raises(SSMDBookError, match="non-standard JSON constant"):
        load_ssmdbook_index(root)


def test_rejects_invalid_utf8_and_malformed_json(tmp_path: Path) -> None:
    root = tmp_path / "book.ssmdbook"
    manifest = _write_manifest(root, _manifest([]))
    manifest.write_bytes(b"\xff")
    with pytest.raises(SSMDBookError, match="invalid ssmdbook manifest"):
        load_ssmdbook_index(root)

    manifest.write_text("{", encoding="utf-8")
    with pytest.raises(SSMDBookError, match="invalid ssmdbook manifest"):
        load_ssmdbook_index(root)


def test_manifest_size_is_limited_before_json_parsing(tmp_path: Path) -> None:
    root = tmp_path / "book.ssmdbook"
    manifest = _write_manifest(root, _manifest([]))
    manifest.write_bytes(b" " * (2 * 1024 * 1024 + 1))

    with pytest.raises(SSMDBookError, match="2 MiB size limit"):
        load_ssmdbook_index(root)


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "/chapters/chapter.ssmd.md",
        "C:/chapters/chapter.ssmd.md",
        "C:chapter.ssmd.md",
        "chapters\\chapter.ssmd.md",
        "chapters/../outside.ssmd.md",
        "chapters/./chapter.ssmd.md",
        "chapters//chapter.ssmd.md",
        "chapters/chapter.ssmd.md/",
        "outside/chapter.ssmd.md",
        "chapters/chapter\x00.ssmd.md",
    ],
)
def test_rejects_unsafe_or_non_normalized_manifest_paths(tmp_path: Path, unsafe_path: str) -> None:
    root = tmp_path / "book.ssmdbook"
    _write_manifest(root, _manifest([_entry(1, path=unsafe_path)]))

    with pytest.raises(SSMDBookError):
        load_ssmdbook_index(root)


@pytest.mark.parametrize(
    "entries",
    [
        [_entry(1), _entry(2, chapter_id="chapter-0001")],
        [_entry(1), _entry(1, chapter_id="other")],
        [_entry(1), _entry(2, path="chapters/chapter-0001.ssmd.md")],
        [{**_entry(1), "source_number": True}],
        [{**_entry(1), "id": " "}],
        [{**_entry(1), "title": 42}],
    ],
)
def test_rejects_invalid_entries_and_duplicate_identity_fields(
    tmp_path: Path, entries: list[object]
) -> None:
    root = tmp_path / "book.ssmdbook"
    _write_manifest(root, _manifest(entries))

    with pytest.raises(SSMDBookError):
        load_ssmdbook_index(root)


def test_selected_missing_file_remains_a_batch_item_read_failure(tmp_path: Path) -> None:
    index = load_ssmdbook_index(_book(tmp_path, (5,)))

    assert selected_chapter_path(index, index.chapters[0]) == (
        index.root / "chapters/chapter-0005.ssmd.md"
    )


def test_rejects_selected_symlink_that_escapes_workspace(tmp_path: Path) -> None:
    root = _book(tmp_path, (5,))
    outside = tmp_path / "outside.ssmd.md"
    outside.write_text("outside", encoding="utf-8")
    link = root / "chapters/chapter-0005.ssmd.md"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    index = load_ssmdbook_index(root)

    with pytest.raises(SSMDBookError, match="escapes workspace"):
        selected_chapter_path(index, index.chapters[0])


def test_rejects_selected_existing_non_file(tmp_path: Path) -> None:
    root = _book(tmp_path, (5,))
    source = root / "chapters/chapter-0005.ssmd.md"
    source.mkdir()
    index = load_ssmdbook_index(root)

    with pytest.raises(SSMDBookError, match="not a regular file"):
        selected_chapter_path(index, index.chapters[0])
