"""UtterPlan-owned metadata and batch projection support for book RenderPlans."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal

import tomlkit
from renderplan import RenderProfile
from renderplan import codec as renderplan_codec
from tomlkit.exceptions import ParseError

from ._version import __version__
from .atomic_io import atomic_write_text
from .exceptions import UtterPlanError
from .model import FlowPlan
from .renderplan_export import build_render_plan

RENDERPLAN_SET_FORMAT = "utterplan-renderplan-set"
RENDERPLAN_SET_VERSION = 1
_PROFILE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{12}$")


class RenderPlanSetError(ValueError):
    """Invalid or unreadable UtterPlan RenderPlan collection metadata."""

    def __init__(self, message: str, *, code: str = "index.invalid") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class RenderPlanSetChapter:
    """One successfully written chapter projection in a RenderPlan set."""

    id: str
    source_number: int
    source: str
    utterplan: str
    source_plan_id: str
    renderplan: str
    render_plan_id: str


@dataclass(frozen=True, slots=True)
class RenderPlanSet:
    """Workspace index for one immutable RenderProfile identity."""

    variant: str
    profile_fingerprint: str
    producer_version: str
    manifest: str
    utterplan_dir: str
    profile_id: str
    snapshot: str
    source_profile: str
    chapters: tuple[RenderPlanSetChapter, ...] = ()

    def __post_init__(self) -> None:
        validate_renderplan_set(self)


def validate_renderplan_set(value: RenderPlanSet) -> None:
    """Reject malformed set values before they are read from or written to disk."""
    _require_nonempty(value.variant, "variant")
    _require_nonempty(value.producer_version, "producer.version")
    _require_nonempty(value.manifest, "book.manifest")
    _require_nonempty(value.utterplan_dir, "book.utterplan_dir")
    _require_nonempty(value.snapshot, "profile.snapshot")
    if value.snapshot != "renderprofile.toml":
        raise RenderPlanSetError("profile.snapshot must be the canonical 'renderprofile.toml' file")
    _require_nonempty(value.source_profile, "profile.source")
    if not _PROFILE_ID_RE.fullmatch(value.profile_id):
        raise RenderPlanSetError("profile.profile_id must be a full sha256 identity")
    if not _FINGERPRINT_RE.fullmatch(value.profile_fingerprint):
        raise RenderPlanSetError("profile_fingerprint must be 12 lowercase hexadecimal characters")
    if value.profile_fingerprint != value.profile_id.removeprefix("sha256:")[:12]:
        raise RenderPlanSetError("profile_fingerprint does not match profile.profile_id")
    if not isinstance(value.chapters, tuple):
        raise RenderPlanSetError("chapter entries must be a tuple")

    seen_ids: set[str] = set()
    seen_numbers: set[int] = set()
    seen_renderplan_paths: set[str] = set()
    for index, chapter in enumerate(value.chapters):
        label = f"chapter[{index}]"
        _require_nonempty(chapter.id, f"{label}.id")
        if type(chapter.source_number) is not int or chapter.source_number <= 0:
            raise RenderPlanSetError(f"{label}.source_number must be a positive integer")
        for key in ("source", "utterplan", "renderplan"):
            _require_nonempty(getattr(chapter, key), f"{label}.{key}")
        renderplan_path = PurePosixPath(chapter.renderplan)
        if (
            "\x00" in chapter.renderplan
            or "\\" in chapter.renderplan
            or renderplan_path.is_absolute()
            or PureWindowsPath(chapter.renderplan).drive
            or not renderplan_path.parts
            or any(part in {".", ".."} for part in renderplan_path.parts)
            or renderplan_path.as_posix() != chapter.renderplan
        ):
            raise RenderPlanSetError(
                f"{label}.renderplan must be a normalized relative path inside the variant"
            )
        for key in ("source_plan_id", "render_plan_id"):
            plan_id = getattr(chapter, key)
            if not _PROFILE_ID_RE.fullmatch(plan_id):
                raise RenderPlanSetError(f"{label}.{key} must be a full sha256 identity")
        if chapter.id in seen_ids:
            raise RenderPlanSetError(f"duplicate chapter id: {chapter.id}")
        if chapter.source_number in seen_numbers:
            raise RenderPlanSetError(f"duplicate chapter source_number: {chapter.source_number}")
        if chapter.renderplan in seen_renderplan_paths:
            raise RenderPlanSetError(f"duplicate renderplan path: {chapter.renderplan}")
        seen_ids.add(chapter.id)
        seen_numbers.add(chapter.source_number)
        seen_renderplan_paths.add(chapter.renderplan)


def renderplan_set_to_dict(value: RenderPlanSet) -> dict[str, Any]:
    """Return the stable plain-data representation for renderplan-set.toml."""
    validate_renderplan_set(value)
    return {
        "format": RENDERPLAN_SET_FORMAT,
        "version": RENDERPLAN_SET_VERSION,
        "variant": value.variant,
        "profile_fingerprint": value.profile_fingerprint,
        "producer": {"name": "utterplan", "version": value.producer_version},
        "book": {"manifest": value.manifest, "utterplan_dir": value.utterplan_dir},
        "profile": {
            "profile_id": value.profile_id,
            "snapshot": value.snapshot,
            "source": value.source_profile,
        },
        "chapter": [
            {
                "id": chapter.id,
                "source_number": chapter.source_number,
                "source": chapter.source,
                "utterplan": chapter.utterplan,
                "source_plan_id": chapter.source_plan_id,
                "renderplan": chapter.renderplan,
                "render_plan_id": chapter.render_plan_id,
            }
            for chapter in value.chapters
        ],
    }


def renderplan_set_to_toml(value: RenderPlanSet) -> str:
    """Serialize a validated set as UtterPlan-owned TOML metadata."""
    return tomlkit.dumps(renderplan_set_to_dict(value))


def renderplan_set_from_dict(raw: Mapping[str, Any]) -> RenderPlanSet:
    """Parse plain TOML data and strictly validate every supported set field."""
    _check_keys(
        raw,
        {"format", "version", "variant", "profile_fingerprint", "producer", "book", "profile", "chapter"},
        "renderplan-set",
    )
    if raw.get("format") != RENDERPLAN_SET_FORMAT:
        raise RenderPlanSetError(f"format must be {RENDERPLAN_SET_FORMAT!r}")
    if type(raw.get("version")) is not int or raw["version"] != RENDERPLAN_SET_VERSION:
        raise RenderPlanSetError(f"version must be {RENDERPLAN_SET_VERSION}")

    producer = _table(raw.get("producer"), "producer")
    _check_keys(producer, {"name", "version"}, "producer")
    if producer.get("name") != "utterplan":
        raise RenderPlanSetError("producer.name must be 'utterplan'")
    book = _table(raw.get("book"), "book")
    _check_keys(book, {"manifest", "utterplan_dir"}, "book")
    profile = _table(raw.get("profile"), "profile")
    _check_keys(profile, {"profile_id", "snapshot", "source"}, "profile")

    chapter_data = raw.get("chapter")
    if not isinstance(chapter_data, list):
        raise RenderPlanSetError("chapter must be an array of tables")
    chapters: list[RenderPlanSetChapter] = []
    chapter_keys = {
        "id",
        "source_number",
        "source",
        "utterplan",
        "source_plan_id",
        "renderplan",
        "render_plan_id",
    }
    for index, item in enumerate(chapter_data):
        item_table = _table(item, f"chapter[{index}]")
        _check_keys(item_table, chapter_keys, f"chapter[{index}]")
        source_number = item_table.get("source_number")
        if type(source_number) is not int:
            raise RenderPlanSetError(f"chapter[{index}].source_number must be an integer")
        chapters.append(
            RenderPlanSetChapter(
                id=_string(item_table, "id", f"chapter[{index}]"),
                source_number=source_number,
                source=_string(item_table, "source", f"chapter[{index}]"),
                utterplan=_string(item_table, "utterplan", f"chapter[{index}]"),
                source_plan_id=_string(item_table, "source_plan_id", f"chapter[{index}]"),
                renderplan=_string(item_table, "renderplan", f"chapter[{index}]"),
                render_plan_id=_string(item_table, "render_plan_id", f"chapter[{index}]"),
            )
        )
    return RenderPlanSet(
        variant=_string(raw, "variant", "renderplan-set"),
        profile_fingerprint=_string(raw, "profile_fingerprint", "renderplan-set"),
        producer_version=_string(producer, "version", "producer"),
        manifest=_string(book, "manifest", "book"),
        utterplan_dir=_string(book, "utterplan_dir", "book"),
        profile_id=_string(profile, "profile_id", "profile"),
        snapshot=_string(profile, "snapshot", "profile"),
        source_profile=_string(profile, "source", "profile"),
        chapters=tuple(chapters),
    )


def load_renderplan_set(path: str | Path) -> RenderPlanSet:
    """Read a set index; malformed documents fail closed instead of being replaced."""
    source = Path(path)
    try:
        raw = tomlkit.parse(source.read_text(encoding="utf-8")).unwrap()
    except (OSError, UnicodeError, ParseError) as exc:
        raise RenderPlanSetError(f"cannot read renderplan set {source}: {exc}", code="index.read_failed") from exc
    if not isinstance(raw, Mapping):
        raise RenderPlanSetError("renderplan-set root must be a table")
    return renderplan_set_from_dict(raw)


def save_renderplan_set(path: str | Path, value: RenderPlanSet) -> None:
    """Atomically write a validated set index."""
    atomic_write_text(path, renderplan_set_to_toml(value), create_parent=True)


def validate_renderplan_set_profile(
    value: RenderPlanSet,
    snapshot_path: str | Path,
    *,
    expected_profile_id: str,
) -> RenderProfile:
    """Verify the set and canonical snapshot against the active RenderProfile identity."""
    validate_renderplan_set(value)
    if value.profile_id != expected_profile_id:
        raise RenderPlanSetError(
            "existing renderplan set profile_id does not match the active RenderProfile",
            code="profile.identity_mismatch",
        )
    snapshot = Path(snapshot_path)
    if not snapshot.is_file():
        raise RenderPlanSetError(
            f"RenderProfile snapshot is missing: {snapshot}", code="profile.snapshot_missing"
        )
    try:
        profile = renderplan_codec.load_profile(snapshot)
    except (OSError, ValueError) as exc:
        raise RenderPlanSetError(
            f"cannot load RenderProfile snapshot {snapshot}: {exc}", code="profile.snapshot_invalid"
        ) from exc
    snapshot_id = profile.profile_id or profile.computed_id()
    if snapshot_id != value.profile_id or snapshot_id != expected_profile_id:
        raise RenderPlanSetError(
            "RenderProfile snapshot identity does not match the set and active profile",
            code="profile.snapshot_mismatch",
        )
    return profile


def new_renderplan_set(
    *,
    variant: str,
    profile_id: str,
    manifest: str,
    utterplan_dir: str,
    source_profile: str,
    chapters: tuple[RenderPlanSetChapter, ...] = (),
) -> RenderPlanSet:
    """Build an empty or populated set with producer and snapshot defaults."""
    return RenderPlanSet(
        variant=variant,
        profile_fingerprint=profile_id.removeprefix("sha256:")[:12],
        producer_version=__version__,
        manifest=manifest,
        utterplan_dir=utterplan_dir,
        profile_id=profile_id,
        snapshot="renderprofile.toml",
        source_profile=source_profile,
        chapters=chapters,
    )


def _check_keys(raw: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(raw) - allowed
    missing = allowed - set(raw)
    if unknown:
        raise RenderPlanSetError(f"{label} contains unknown field(s): {', '.join(sorted(unknown))}")
    if missing:
        raise RenderPlanSetError(f"{label} is missing required field(s): {', '.join(sorted(missing))}")


def _table(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RenderPlanSetError(f"{label} must be a table")
    return value


def _string(raw: Mapping[str, Any], key: str, label: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise RenderPlanSetError(f"{label}.{key} must be a non-empty string")
    return value


def _require_nonempty(value: str, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise RenderPlanSetError(f"{label} must be a non-empty string")


RenderBatchStatus = Literal["written", "failed", "skipped"]
RenderBatchStage = Literal["load", "projection", "serialization", "write", "index"]


@dataclass(frozen=True, slots=True)
class RenderRequest:
    """One semantic UtterPlan input and its independent RenderPlan output."""

    id: str
    source_number: int
    source_plan: Path
    output: Path
    source_chapter: Path

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("render request id must be non-empty")
        if type(self.source_number) is not int or self.source_number <= 0:
            raise ValueError("render request source_number must be a positive integer")
        object.__setattr__(self, "source_plan", Path(self.source_plan))
        object.__setattr__(self, "output", Path(self.output))
        object.__setattr__(self, "source_chapter", Path(self.source_chapter))


@dataclass(frozen=True, slots=True)
class RenderOutcome:
    """Operational result for one chapter projection; plan objects are not retained."""

    id: str
    source_number: int
    index: int
    total: int | None
    status: RenderBatchStatus
    source_plan: Path
    output: Path
    source_plan_id: str | None = None
    render_plan_id: str | None = None
    stage: RenderBatchStage | None = None
    error_code: str | None = None
    error_message: str | None = None


def render_to_files(
    requests: Sequence[RenderRequest],
    *,
    profile: RenderProfile,
    renderplan_set: RenderPlanSet,
    set_path: str | Path,
    report_path: str | Path,
    force: bool = False,
    fail_fast: bool = False,
    chapter_order: Mapping[str, int] | None = None,
    on_progress: Callable[[RenderOutcome], None] | None = None,
) -> list[RenderOutcome]:
    """Project and persist chapters incrementally, keeping successful outputs on failure."""
    validate_renderplan_set(renderplan_set)
    profile_id = profile.profile_id or profile.computed_id()
    if profile_id != renderplan_set.profile_id:
        raise RenderPlanSetError(
            "renderplan set profile_id does not match the active RenderProfile",
            code="profile.identity_mismatch",
        )
    selected_set_path = Path(set_path)
    selected_report_path = Path(report_path)
    _validate_render_requests(requests, renderplan_set, selected_set_path)

    outcomes: list[RenderOutcome] = []
    _write_render_report(
        selected_report_path,
        outcomes,
        requested=len(requests),
        complete=False,
        value=renderplan_set,
    )
    stopped = False
    active_set = renderplan_set
    for index, request in enumerate(requests, start=1):
        if stopped:
            outcome = RenderOutcome(
                id=request.id,
                source_number=request.source_number,
                index=index,
                total=len(requests),
                status="skipped",
                source_plan=request.source_plan,
                output=request.output,
                error_code="batch.fail_fast",
                error_message="Skipped after an earlier failure because fail_fast is enabled.",
            )
        else:
            outcome, updated_set = _render_one(
                request,
                index=index,
                total=len(requests),
                profile=profile,
                renderplan_set=active_set,
                set_path=selected_set_path,
                force=force,
                chapter_order=chapter_order or {},
            )
            if outcome.status == "written":
                active_set = updated_set
        outcomes.append(outcome)
        _write_render_report(
            selected_report_path,
            outcomes,
            requested=len(requests),
            complete=False,
            value=renderplan_set,
        )
        if on_progress is not None:
            on_progress(outcome)
        if fail_fast and outcome.status == "failed":
            stopped = True

    _write_render_report(
        selected_report_path,
        outcomes,
        requested=len(requests),
        complete=True,
        value=renderplan_set,
    )
    return outcomes


def _validate_render_requests(
    requests: Sequence[RenderRequest], value: RenderPlanSet, set_path: Path
) -> None:
    seen_ids: set[str] = set()
    seen_outputs: set[Path] = set()
    existing_owners = {
        (set_path.parent / chapter.renderplan).resolve(): chapter.id for chapter in value.chapters
    }
    for request in requests:
        output = request.output.resolve()
        if request.id in seen_ids:
            raise RenderPlanSetError(f"duplicate selected chapter id: {request.id}")
        if output in seen_outputs:
            raise RenderPlanSetError(f"duplicate selected RenderPlan output path: {request.output}")
        owner = existing_owners.get(output)
        if owner is not None and owner != request.id:
            raise RenderPlanSetError(
                f"RenderPlan output {request.output} is already assigned to chapter {owner}"
            )
        seen_ids.add(request.id)
        seen_outputs.add(output)


def _render_one(
    request: RenderRequest,
    *,
    index: int,
    total: int,
    profile: RenderProfile,
    renderplan_set: RenderPlanSet,
    set_path: Path,
    force: bool,
    chapter_order: Mapping[str, int],
) -> tuple[RenderOutcome, RenderPlanSet]:
    output = request.output
    if not force and output.exists():
        return (
            _render_failure(
                request,
                index=index,
                total=total,
                stage="write",
                error_code="output.exists",
                error_message=f"output already exists: {output}; use --force to replace it",
            ),
            renderplan_set,
        )
    if not request.source_plan.is_file():
        code = "input.missing" if not request.source_plan.exists() else "input.read_failed"
        return (
            _render_failure(
                request,
                index=index,
                total=total,
                stage="load",
                error_code=code,
                error_message=f"cannot read UtterPlan input: {request.source_plan}",
            ),
            renderplan_set,
        )
    try:
        source_plan = FlowPlan.load(request.source_plan)
    except (OSError, UtterPlanError, ValueError, TypeError) as exc:
        return (
            _render_failure(
                request,
                index=index,
                total=total,
                stage="load",
                error_code=_error_code(exc, "input.plan_invalid"),
                error_message=str(exc),
            ),
            renderplan_set,
        )

    source_plan_id = source_plan.plan_id
    try:
        plan = build_render_plan(source_plan, profile).with_identity()
    except (OSError, ValueError, TypeError) as exc:
        return (
            _render_failure(
                request,
                index=index,
                total=total,
                stage="projection",
                error_code=_error_code(exc, "renderplan.projection_failed"),
                error_message=str(exc),
                source_plan_id=source_plan_id,
            ),
            renderplan_set,
        )

    try:
        renderplan_codec.plan_to_dict(plan)
    except (OSError, ValueError, TypeError) as exc:
        return (
            _render_failure(
                request,
                index=index,
                total=total,
                stage="serialization",
                error_code=_error_code(exc, "renderplan.serialization_failed"),
                error_message=str(exc),
                source_plan_id=source_plan_id,
            ),
            renderplan_set,
        )
    try:
        renderplan_codec.save_plan(plan, output)
    except (OSError, ValueError, TypeError) as exc:
        return (
            _render_failure(
                request,
                index=index,
                total=total,
                stage="write",
                error_code=_error_code(exc, "output.write_failed"),
                error_message=str(exc),
                source_plan_id=source_plan_id,
            ),
            renderplan_set,
        )

    render_plan_id = plan.plan_id or plan.computed_id()
    entry = RenderPlanSetChapter(
        id=request.id,
        source_number=request.source_number,
        source=_path_reference(request.source_chapter, set_path.parent),
        utterplan=_path_reference(request.source_plan, set_path.parent),
        source_plan_id=source_plan_id,
        renderplan=_path_reference(output, set_path.parent),
        render_plan_id=render_plan_id,
    )
    try:
        updated_set = _upsert_renderplan_set(renderplan_set, entry, chapter_order)
        save_renderplan_set(set_path, updated_set)
    except (OSError, ValueError, TypeError) as exc:
        return (
            _render_failure(
                request,
                index=index,
                total=total,
                stage="index",
                error_code=_error_code(exc, "index.write_failed"),
                error_message=str(exc),
                source_plan_id=source_plan_id,
                render_plan_id=render_plan_id,
            ),
            renderplan_set,
        )
    return (
        RenderOutcome(
            id=request.id,
            source_number=request.source_number,
            index=index,
            total=total,
            status="written",
            source_plan=request.source_plan,
            output=output,
            source_plan_id=source_plan_id,
            render_plan_id=render_plan_id,
        ),
        updated_set,
    )


def _upsert_renderplan_set(
    value: RenderPlanSet, entry: RenderPlanSetChapter, chapter_order: Mapping[str, int]
) -> RenderPlanSet:
    previous_order = {chapter.id: index for index, chapter in enumerate(value.chapters)}
    chapters_by_id = {chapter.id: chapter for chapter in value.chapters}
    chapters_by_id[entry.id] = entry
    chapters = tuple(
        sorted(
            chapters_by_id.values(),
            key=lambda chapter: (
                0 if chapter.id in chapter_order else 1,
                chapter_order.get(chapter.id, previous_order.get(chapter.id, len(chapter_order))),
            ),
        )
    )
    return replace(value, chapters=chapters)


def _path_reference(path: Path, base: Path) -> str:
    return Path(os.path.relpath(path.resolve(), start=base.resolve())).as_posix()


def _render_failure(
    request: RenderRequest,
    *,
    index: int,
    total: int,
    stage: RenderBatchStage,
    error_code: str,
    error_message: str,
    source_plan_id: str | None = None,
    render_plan_id: str | None = None,
) -> RenderOutcome:
    return RenderOutcome(
        id=request.id,
        source_number=request.source_number,
        index=index,
        total=total,
        status="failed",
        source_plan=request.source_plan,
        output=request.output,
        source_plan_id=source_plan_id,
        render_plan_id=render_plan_id,
        stage=stage,
        error_code=error_code,
        error_message=error_message,
    )


def _write_render_report(
    path: Path,
    outcomes: Sequence[RenderOutcome],
    *,
    requested: int,
    complete: bool,
    value: RenderPlanSet,
) -> None:
    items: list[dict[str, Any]] = []
    for outcome in outcomes:
        item: dict[str, Any] = {
            "index": outcome.index,
            "id": outcome.id,
            "source_number": outcome.source_number,
            "source": str(outcome.source_plan.resolve()),
            "output": str(outcome.output.resolve()),
            "status": outcome.status,
        }
        if outcome.source_plan_id is not None:
            item["source_plan_id"] = outcome.source_plan_id
        if outcome.render_plan_id is not None:
            item["render_plan_id"] = outcome.render_plan_id
        if outcome.stage is not None:
            item["stage"] = outcome.stage
        if outcome.error_code is not None:
            item["code"] = outcome.error_code
        if outcome.error_message is not None:
            item["message"] = outcome.error_message
        items.append(item)
    counts = {status: sum(outcome.status == status for outcome in outcomes) for status in ("written", "failed", "skipped")}
    report = {
        "format": "utterplan-render-report",
        "version": 1,
        "requested": requested,
        "written": counts["written"],
        "failed": counts["failed"],
        "skipped": counts["skipped"],
        "complete": complete,
        "variant": value.variant,
        "profile_id": value.profile_id,
        "item": items,
    }
    atomic_write_text(path, tomlkit.dumps(report), create_parent=True)


def _error_code(error: Exception, fallback: str) -> str:
    code = getattr(error, "code", None)
    return code if isinstance(code, str) and code else fallback


__all__ = [
    "RENDERPLAN_SET_FORMAT",
    "RENDERPLAN_SET_VERSION",
    "RenderBatchStage",
    "RenderBatchStatus",
    "RenderOutcome",
    "RenderRequest",
    "RenderPlanSet",
    "RenderPlanSetChapter",
    "RenderPlanSetError",
    "load_renderplan_set",
    "new_renderplan_set",
    "renderplan_set_from_dict",
    "renderplan_set_to_dict",
    "renderplan_set_to_toml",
    "save_renderplan_set",
    "validate_renderplan_set",
    "render_to_files",
    "validate_renderplan_set_profile",
]
