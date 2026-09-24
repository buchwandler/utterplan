from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .config import PlannerConfig, parse_duration
from .exceptions import ConfigurationError, PlanFormatError, PlanningError
from .model import AnnotationSpan, BoundaryEvent, Diagnostic, Marker


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    source_text: str
    structural_text: str
    annotations: tuple[AnnotationSpan, ...] = ()
    boundaries: tuple[BoundaryEvent, ...] = ()
    markers: tuple[Marker, ...] = ()
    header: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    document_language: str = ""


class PlainDocumentParser:
    def parse(self, text: str, config: PlannerConfig) -> ParsedDocument:
        boundaries = tuple(
            BoundaryEvent(
                id=f"boundary-{index:06d}",
                position=match.start(),
                kind="paragraph",
                origin="plain",
                strength="paragraph",
            )
            for index, match in enumerate(re.finditer(r"\n\s*\n", text))
        )
        return ParsedDocument(
            source_text=text,
            structural_text=text,
            boundaries=boundaries,
            document_language=config.language,
        )


class SSMDDocumentParser:
    def parse(self, text: str, config: PlannerConfig) -> ParsedDocument:
        try:
            import ssmd
            from ssmd.frontmatter import FrontMatterError
        except ImportError as exc:
            raise PlanningError("SSMD input requires the ssmd package") from exc

        try:
            parsed = ssmd.parse_structure(
                text,
                default_lang=None,
                parse_yaml_header=config.ssmd.parse_yaml_header,
                resolve_defaults=False,
                dialect="0.9",
            )
        except FrontMatterError as exc:
            location = _format_location(exc.line, exc.column)
            raise PlanFormatError(f"{exc}{location}", code=exc.code, path="$.source") from exc

        diagnostics = tuple(_ssmd_diagnostic(item) for item in parsed.diagnostics)
        errors = [item for item in diagnostics if item.severity == "error"]
        if errors:
            first = errors[0]
            location = _format_location(first.line, first.column)
            raise PlanFormatError(f"{first.message}{location}", code=first.code, path="$.source")

        structural = str(parsed.clean_text)
        annotations = tuple(
            AnnotationSpan(
                id=f"annotation-{i:06d}",
                kind=str(getattr(item, "kind", "annotation")),
                attrs={str(k): _plain_value(v) for k, v in item.attrs.items()},
                structural_start=int(item.char_start),
                structural_end=int(item.char_end),
                source_start=getattr(item, "source_start", None),
                source_end=getattr(item, "source_end", None),
                source_node_id=(
                    str(item.node_id) if getattr(item, "node_id", None) is not None else None
                ),
            )
            for i, item in enumerate(parsed.annotations)
            if int(item.char_end) > int(item.char_start)
        )
        boundaries: list[BoundaryEvent] = []
        markers: list[Marker] = []
        warnings = [str(value) for value in parsed.warnings]
        for event in parsed.events:
            attrs = {str(k): _plain_value(v) for k, v in event.attrs.items()}
            kind = str(event.kind)
            position = int(getattr(event, "pos", getattr(event, "position", 0)))
            event_anchor = str(getattr(event, "anchor", attrs.get("anchor", "after")))
            if kind == "mark":
                name = attrs.get("name") or attrs.get("marker") or "marker"
                markers.append(Marker(f"marker-{len(markers):06d}", str(name), position, attrs))
            elif kind == "break":
                seconds = _duration(attrs, config, parsed.header)
                boundaries.append(
                    BoundaryEvent(
                        id=f"boundary-{len(boundaries):06d}",
                        position=position,
                        kind="explicit",
                        seconds=seconds,
                        origin="ssmd",
                        strength=attrs.get("strength"),
                        attrs={
                            **attrs,
                            "anchor": event_anchor,
                            "pause_origin": _duration_origin(attrs, config, parsed.header),
                        },
                    )
                )
            elif kind == "paragraph":
                paragraph_origin = _duration_origin(
                    {**attrs, "strength": "x-strong"}, config, parsed.header
                )
                if paragraph_origin == "none":
                    paragraph_origin = "planner_default"
                boundaries.append(
                    BoundaryEvent(
                        id=f"boundary-{len(boundaries):06d}",
                        position=position,
                        kind="paragraph",
                        seconds=_duration(attrs, config, parsed.header),
                        origin="ssmd",
                        strength=attrs.get("strength", "paragraph"),
                        attrs={
                            **attrs,
                            "anchor": event_anchor,
                            "strength": "p",
                            "source": paragraph_origin,
                            "pause_origin": paragraph_origin,
                        },
                    )
                )
            elif kind == "heading":
                boundaries.append(
                    BoundaryEvent(
                        id=f"boundary-{len(boundaries):06d}",
                        position=position,
                        kind="heading",
                        seconds=0.0,
                        origin="ssmd",
                        attrs={**attrs, "anchor": event_anchor, "structural_only": True},
                    )
                )

        header = _plain_value(parsed.header)
        metadata: dict[str, Any] = {"header": header}
        for key in (
            "ssmd_version",
            "title",
            "language",
            "voice_bindings",
            "voice_defaults",
            "pause_defaults",
            "prosody_transitions",
            "language_detection",
            "requires",
        ):
            if key in header:
                metadata[key] = header[key]

        document_language = header.get("language") if config.ssmd.parse_yaml_header else None
        if not isinstance(document_language, str) or not document_language:
            document_language = config.language

        return ParsedDocument(
            source_text=text,
            structural_text=structural,
            annotations=annotations,
            boundaries=tuple(boundaries),
            markers=tuple(markers),
            header=header,
            metadata=metadata,
            warnings=tuple(warnings),
            diagnostics=tuple(item for item in diagnostics if item.severity != "error"),
            document_language=document_language,
        )


def _plain_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _ssmd_diagnostic(item: Any) -> Diagnostic:
    return Diagnostic(
        code=str(item.code),
        message=str(item.message),
        severity=str(item.severity),
        path="$.source",
        source_start=getattr(item, "source_start", None),
        source_end=getattr(item, "source_end", None),
        line=getattr(item, "line", None),
        column=getattr(item, "column", None),
        hint=getattr(item, "hint", None),
    )


def _format_location(line: int | None, column: int | None) -> str:
    if line is None:
        return ""
    location = f" at line {line}"
    if column is not None:
        location += f", column {column}"
    return location


def _duration(
    attrs: dict[str, Any], config: PlannerConfig, header: dict[str, Any] | None = None
) -> float | None:
    value = attrs.get("time")
    if value is not None:
        try:
            return parse_duration(value, field_name="break.time")
        except ConfigurationError as exc:
            raise PlanFormatError(str(exc), code="break.duration") from exc

    strength = str(attrs.get("strength", "")).lower()
    key = {
        "x-weak": "weak",
        "weak": "weak",
        "medium": "clause",
        "strong": "sentence",
        "x-strong": "paragraph",
    }.get(strength)
    defaults: dict[str, Any] = {
        "weak": config.pauses.weak,
        "clause": config.pauses.clause,
        "sentence": config.pauses.sentence,
        "paragraph": config.pauses.paragraph,
        "parenthetical": config.pauses.parenthetical,
        "voice_change": config.pauses.voice_change,
    }
    if header and isinstance(header.get("pause_defaults"), dict):
        for name, candidate in header["pause_defaults"].items():
            if name == "enabled":
                continue
            try:
                parse_duration(candidate, field_name=f"pause_defaults.{name}")
            except ConfigurationError:
                continue
            defaults[name] = candidate
    if config.ssmd.pause_overrides:
        defaults.update(config.ssmd.pause_overrides)
    if not _pause_enabled(config, header):
        return None
    if key in defaults:
        try:
            return parse_duration(defaults[key], field_name=f"pause_defaults.{key}")
        except ConfigurationError as exc:
            raise PlanFormatError(str(exc), code="pause.duration") from exc
    return None


def _pause_enabled(config: PlannerConfig, header: dict[str, Any] | None) -> bool:
    enabled = config.pauses.enabled
    if header and isinstance(header.get("pause_defaults"), dict):
        value = header["pause_defaults"].get("enabled")
        if isinstance(value, bool):
            enabled = value
    if config.ssmd.pause_overrides and "enabled" in config.ssmd.pause_overrides:
        enabled = bool(config.ssmd.pause_overrides["enabled"])
    return enabled


def _duration_origin(attrs: dict[str, Any], config: PlannerConfig, header: dict[str, Any]) -> str:
    if attrs.get("time") is not None:
        return "explicit"
    strength = str(attrs.get("strength", "")).lower()
    key = {
        "x-weak": "weak",
        "weak": "weak",
        "medium": "clause",
        "strong": "sentence",
        "x-strong": "paragraph",
    }.get(strength)
    if config.ssmd.pause_overrides and key in config.ssmd.pause_overrides:
        return "config_default"
    header_defaults = header.get("pause_defaults")
    if isinstance(header_defaults, dict) and header_defaults.get(key) is not None:
        try:
            parse_duration(header_defaults[key], field_name=f"pause_defaults.{key}")
        except ConfigurationError:
            return "planner_default"
        return "header_default"
    return "planner_default" if key else "none"
