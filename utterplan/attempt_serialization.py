"""Serialization for the separate planning-attempt v1 artifact."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

import tomlkit
from tomlkit.exceptions import ParseError

from ._version import __version__
from .attempts import PlanDraft, PlanningAttempt, planning_attempt_id
from .codecs.v4_toml import _mapping, _omit_none, _plain_toml, _toml_item
from .exceptions import PlanFormatError
from .hashing import semantic_hash
from .model import _from_current_dict, validate_plan_structure
from .renderability import RenderabilityIssue, RenderabilityRepair, RenderabilityReport

ATTEMPT_SCHEMA = "utterplan.planning-attempt.v1"


def planning_attempt_to_dict(attempt: PlanningAttempt) -> dict[str, Any]:
    """Return plain data for an attempt, distinct from the canonical plan mapping."""
    plan = attempt.candidate._plan
    return {
        "schema": ATTEMPT_SCHEMA,
        "attempt": {
            "schema": ATTEMPT_SCHEMA,
            "attempt_id": attempt.attempt_id,
            "status": attempt.status,
            "created_by_version": __version__,
            "renderability_mode": attempt.renderability_mode,
            "input_sha256": hashlib.sha256(plan.source.text.encode("utf-8")).hexdigest(),
            "semantic_fingerprint": semantic_hash(plan.semantic_dict()),
        },
        "candidate": plan.to_dict(),
        "renderability": {
            "checked_segments": attempt.renderability.checked_segments,
            "guaranteed": attempt.ok,
            "repair_count": len(attempt.repairs),
            "issues": [asdict(issue) for issue in attempt.renderability.issues],
            "assessments": [asdict(issue) for issue in attempt.renderability.repairs],
            "repairs": [asdict(issue) for issue in attempt.repairs],
        },
        "diagnostics": [diagnostic.to_dict() for diagnostic in attempt.diagnostics],
    }


def dumps_planning_attempt(attempt: PlanningAttempt) -> str:
    """Serialize an attempt as a distinct, deterministic TOML artifact."""
    plan = attempt.candidate._plan
    report = {
        "checked_segments": attempt.renderability.checked_segments,
        "guaranteed": attempt.ok,
        "repair_count": len(attempt.repairs),
        "issues": [_omit_none(asdict(issue)) for issue in attempt.renderability.issues],
        "assessments": [_omit_none(asdict(issue)) for issue in attempt.renderability.repairs],
        "repairs": [_omit_none(asdict(issue)) for issue in attempt.repairs],
    }
    wire = {
        "attempt": planning_attempt_to_dict(attempt)["attempt"],
        "candidate_json": json.dumps(
            plan.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
        "renderability": report,
    }
    document = tomlkit.document()
    for key, value in wire.items():
        document[key] = _toml_item(value, (key,))
    return tomlkit.dumps(document)


def loads_planning_attempt(value: object) -> PlanningAttempt:
    """Parse and validate one planning-attempt TOML artifact."""
    if not isinstance(value, str):
        raise PlanFormatError("TOML input must be text", code="toml.type")
    try:
        parsed = tomlkit.parse(value)
    except ParseError as exc:
        line = getattr(exc, "line", None)
        column = getattr(exc, "col", None)
        location = f"line {line}, column {column}: " if line is not None else ""
        raise PlanFormatError(f"{location}{exc}", code="toml.invalid") from exc

    root = _plain_toml(parsed.unwrap())
    if not isinstance(root, Mapping):
        raise PlanFormatError("attempt artifact must be a TOML table", code="field.type")
    unknown = set(root) - {"attempt", "candidate_json", "renderability"}
    if unknown:
        raise PlanFormatError(
            f"unknown planning-attempt fields: {sorted(unknown)}", code="field.unknown"
        )
    try:
        manifest = _mapping(root["attempt"], "$.attempt")
        candidate_json = root["candidate_json"]
        if not isinstance(candidate_json, str):
            raise PlanFormatError("candidate_json must be text", code="field.type")
        try:
            candidate_data = json.loads(candidate_json)
        except json.JSONDecodeError as exc:
            raise PlanFormatError("candidate_json must contain JSON", code="field.json") from exc
        candidate_mapping = _mapping(candidate_data, "$.candidate_json")
        report_data = _mapping(root["renderability"], "$.renderability")
        if manifest.get("schema") != ATTEMPT_SCHEMA:
            raise PlanFormatError(
                f"schema must be {ATTEMPT_SCHEMA!r}", code="attempt.schema", path="$.attempt.schema"
            )
        status = manifest.get("status")
        if status not in {"renderable", "repaired", "blocked"}:
            raise PlanFormatError("invalid planning-attempt status", code="attempt.status")
        mode = manifest.get("renderability_mode")
        if mode not in {"strict", "repair"}:
            raise PlanFormatError("invalid renderability mode", code="attempt.mode")
        attempt_id = manifest.get("attempt_id")
        if not isinstance(attempt_id, str):
            raise PlanFormatError("attempt_id must be text", code="attempt.id")
        for name in ("created_by_version", "input_sha256", "semantic_fingerprint"):
            if not isinstance(manifest.get(name), str):
                raise PlanFormatError(
                    f"{name} must be text", code="field.type", path=f"$.attempt.{name}"
                )
        plan = _from_current_dict(candidate_mapping)
        validate_plan_structure(plan)
        checked_segments = report_data.get("checked_segments")
        repair_count = report_data.get("repair_count")
        guaranteed = report_data.get("guaranteed")
        if type(checked_segments) is not int or checked_segments < 0:
            raise PlanFormatError(
                "checked_segments must be a non-negative integer", code="field.type"
            )
        if type(repair_count) is not int or repair_count < 0:
            raise PlanFormatError("repair_count must be a non-negative integer", code="field.type")
        if type(guaranteed) is not bool:
            raise PlanFormatError("guaranteed must be a boolean", code="field.type")
        issues = tuple(
            _issue_from_dict(item, "$.renderability.issues")
            for item in _array(report_data, "issues")
        )
        assessments = tuple(
            _issue_from_dict(item, "$.renderability.assessments")
            for item in _array(report_data, "assessments")
        )
        repairs = tuple(
            _issue_from_dict(item, "$.renderability.repairs")
            for item in _array(report_data, "repairs")
        )
        report = RenderabilityReport(checked_segments, issues, assessments)
        if repair_count != len(repairs) or guaranteed != (status in {"renderable", "repaired"}):
            raise PlanFormatError(
                "renderability summary does not match status", code="attempt.report"
            )
        if status == "blocked" and not issues:
            raise PlanFormatError(
                "blocked attempts require renderability issues", code="attempt.report"
            )
        if status == "renderable" and (issues or assessments or repairs):
            raise PlanFormatError(
                "renderable attempts cannot contain issues or repairs", code="attempt.report"
            )
        if status == "repaired" and (issues or not repairs):
            raise PlanFormatError(
                "repaired attempts require repairs and no remaining issues", code="attempt.report"
            )
        if status == "blocked" and plan.plan_id:
            raise PlanFormatError(
                "blocked candidate cannot have a canonical plan_id", code="attempt.identity"
            )
        expected_input_hash = hashlib.sha256(plan.source.text.encode("utf-8")).hexdigest()
        if manifest["input_sha256"] != expected_input_hash:
            raise PlanFormatError(
                "input_sha256 does not match candidate source", code="attempt.input_hash"
            )
        if manifest["semantic_fingerprint"] != semantic_hash(plan.semantic_dict()):
            raise PlanFormatError(
                "semantic fingerprint does not match candidate", code="attempt.fingerprint"
            )
        expected_attempt_id = planning_attempt_id(
            status=status,
            plan=plan,
            report=report,
            renderability_mode=mode,
        )
        if attempt_id != expected_attempt_id:
            raise PlanFormatError(
                "attempt_id does not match candidate state", code="attempt.identity"
            )
        return PlanningAttempt(
            status=status,
            candidate=PlanDraft(plan, report),
            renderability=report,
            diagnostics=plan.diagnostics,
            repairs=repairs,
            attempt_id=attempt_id,
            renderability_mode=mode,
        )
    except KeyError as exc:
        raise PlanFormatError(
            f"required planning-attempt field {exc.args[0]!r} is missing", code="field.required"
        ) from exc
    except (TypeError, ValueError, IndexError) as exc:
        if isinstance(exc, PlanFormatError):
            raise
        raise PlanFormatError(
            f"invalid planning-attempt value: {exc}", code="attempt.value"
        ) from exc


def _array(data: Mapping[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list):
        raise PlanFormatError(
            "expected a TOML array", code="field.type", path=f"$.renderability.{key}"
        )
    return value


def _issue_from_dict(value: object, path: str) -> RenderabilityIssue:
    if not isinstance(value, Mapping):
        raise PlanFormatError("renderability issue must be a table", code="field.type", path=path)
    data = dict(value)
    assessment = data.get("repair_assessment")
    if assessment is not None:
        if not isinstance(assessment, Mapping):
            raise PlanFormatError("repair assessment must be a table", code="field.type", path=path)
        assessment_data = dict(assessment)
        if "blockers" in assessment_data:
            assessment_data["blockers"] = tuple(assessment_data["blockers"])
        data["repair_assessment"] = RenderabilityRepair(**assessment_data)
    for key in ("token_pos", "token_ids"):
        if key in data:
            data[key] = tuple(data[key])
    if "source_context" in data:
        data["source_context"] = tuple(tuple(item) for item in data["source_context"])
    try:
        return RenderabilityIssue(**data)
    except TypeError as exc:
        raise PlanFormatError(
            f"invalid renderability issue: {exc}", code="attempt.issue", path=path
        ) from exc


__all__ = [
    "ATTEMPT_SCHEMA",
    "dumps_planning_attempt",
    "loads_planning_attempt",
    "planning_attempt_to_dict",
]
