from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from .config import LinguisticsConfig
from .language import LanguageRun
from .model import TokenAnnotation
from .spacy_models import resolve_spacy_model


@dataclass(frozen=True, slots=True)
class RunAnalysis:
    """Request-local linguistic state. Never serialize this object."""

    language: str
    start: int
    end: int
    tokens: tuple[TokenAnnotation, ...]
    provider_doc: object | None = None
    provider: Literal["spacy", "fallback"] = "fallback"
    model_name: str | None = None
    provider_version: str | None = None
    model_version: str | None = None


@dataclass(frozen=True, slots=True)
class LinguisticAnalysis:
    language: str
    text: str
    tokens: tuple[TokenAnnotation, ...]
    provider: Literal["spacy", "fallback"] = "fallback"
    model_name: str | None = None
    provider_version: str | None = None
    model_version: str | None = None
    provider_doc: object | None = None


class LinguisticResourcePool:
    """Cache local spaCy pipelines without downloading a model."""

    def __init__(self) -> None:
        self._pipelines: dict[str, Any] = {}

    def pipeline(self, model: str | None, *, require: bool = False) -> Any | None:
        if not model:
            return None
        if model in self._pipelines:
            return self._pipelines[model]
        try:
            import spacy

            pipeline = spacy.load(model)
        except (ImportError, OSError, ValueError) as exc:
            if require:
                raise RuntimeError(f"Requested spaCy model {model!r} is unavailable") from exc
            return None
        self._pipelines[model] = pipeline
        return pipeline

    def clear(self) -> None:
        self._pipelines.clear()

    def _select_model(self, language: str, config: LinguisticsConfig) -> str | None:
        if config.spacy_model:
            return config.spacy_model
        if config.spacy_model_size:
            return resolve_spacy_model(language, config.spacy_model_size)
        if config.use_spacy is False:
            return None
        if config.use_spacy is not True:
            return None
        try:
            import spacy

            installed = set(spacy.util.get_installed_models())
        except ImportError:
            return None
        base = language.split("-", 1)[0].lower()
        families = (f"{base}_core_web_", f"{base}_core_news_")
        for suffix in ("trf", "lg", "md", "sm"):
            for family in families:
                candidate = family + suffix
                if candidate in installed:
                    return candidate
        return None

    def analyze(self, text: str, run: LanguageRun, config: LinguisticsConfig) -> LinguisticAnalysis:
        model = self._select_model(run.language, config)
        use_spacy = config.use_spacy if config.use_spacy is not None else model is not None
        if use_spacy:
            pipeline = self.pipeline(model, require=config.require_spacy)
            if pipeline is not None:
                doc = pipeline(text)
                provider_version = _spacy_version()
                model_version = _model_version(pipeline)
                return LinguisticAnalysis(
                    language=run.language,
                    text=text,
                    tokens=tuple(
                        TokenAnnotation(
                            spoken_start=int(token.idx),
                            spoken_end=int(token.idx + len(token.text)),
                            text=str(token.text),
                            pos=getattr(token, "pos_", None) or None,
                            tag=getattr(token, "tag_", None) or None,
                            lemma=getattr(token, "lemma_", None) or None,
                            language=run.language,
                            id=f"token-{i}",
                            morph=str(getattr(token, "morph", "") or "") or None,
                        )
                        for i, token in enumerate(doc)
                        if token.text
                    ),
                    provider="spacy",
                    model_name=model,
                    provider_version=provider_version,
                    model_version=model_version,
                    provider_doc=doc,
                )
            if config.require_spacy:
                raise RuntimeError("spaCy is required but no local model is available")
        return LinguisticAnalysis(
            language=run.language,
            text=text,
            tokens=_fallback_tokens(text, run.language),
            provider="fallback",
        )


def _spacy_version() -> str | None:
    try:
        import spacy
    except ImportError:
        return None
    value = getattr(spacy, "__version__", None)
    return str(value) if value else None


def _model_version(pipeline: Any) -> str | None:
    metadata = getattr(pipeline, "meta", None)
    if isinstance(metadata, dict):
        value = metadata.get("version")
        return str(value) if value else None
    return None


def _fallback_tokens(text: str, language: str) -> tuple[TokenAnnotation, ...]:
    return tuple(
        TokenAnnotation(
            spoken_start=match.start(),
            spoken_end=match.end(),
            text=match.group(0),
            lemma=match.group(0).lower(),
            language=language,
            id=f"token-{i}",
        )
        for i, match in enumerate(re.finditer(r"\S+", text))
    )


def analyze_run_analyses(
    text: str,
    runs: tuple[LanguageRun, ...],
    config: LinguisticsConfig,
    pool: LinguisticResourcePool,
) -> tuple[RunAnalysis, ...]:
    analyses: list[RunAnalysis] = []
    for run in runs:
        local = text[run.spoken_start : run.spoken_end]
        analysis = pool.analyze(local, run, config)
        offset = run.spoken_start
        tokens = tuple(
            TokenAnnotation(
                spoken_start=token.spoken_start + offset,
                spoken_end=token.spoken_end + offset,
                text=token.text,
                pos=token.pos,
                tag=token.tag,
                lemma=token.lemma,
                language=token.language,
                id=f"token-{sum(len(item.tokens) for item in analyses) + i}",
                morph=token.morph,
            )
            for i, token in enumerate(analysis.tokens)
        )
        analyses.append(
            RunAnalysis(
                language=run.language,
                start=run.spoken_start,
                end=run.spoken_end,
                tokens=tokens,
                provider_doc=analysis.provider_doc,
                provider=analysis.provider,
                model_name=analysis.model_name,
                provider_version=analysis.provider_version,
                model_version=analysis.model_version,
            )
        )
    return tuple(analyses)


def analyze_runs(
    text: str,
    runs: tuple[LanguageRun, ...],
    config: LinguisticsConfig,
    pool: LinguisticResourcePool,
) -> tuple[TokenAnnotation, ...]:
    return tuple(
        token
        for analysis in analyze_run_analyses(text, runs, config, pool)
        for token in analysis.tokens
    )
