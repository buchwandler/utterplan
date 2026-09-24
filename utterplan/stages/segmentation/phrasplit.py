from __future__ import annotations

from ...config import PlannerConfig
from ...language import language_lookup_key
from ...model import PlanSegment


def split_text(text: str, config: PlannerConfig) -> tuple[PlanSegment, ...]:
    try:
        import phrasplit

        items = phrasplit.split_with_offsets(
            text, mode="sentence", use_spacy=False, language=language_lookup_key(config.language)
        )
    except (ImportError, OSError, TypeError, ValueError):
        items = ()
    result = []
    for index, item in enumerate(items):
        start, end = int(item.char_start), int(item.char_end)
        result.append(
            PlanSegment(
                f"seg-{index:06d}",
                text[start:end],
                start,
                end,
                config.language,
                int(getattr(item, "paragraph_idx", 0) or 0),
                int(getattr(item, "sentence_idx", 0) or 0),
            )
        )
    if not result and text:
        result.append(PlanSegment("seg-000000", text, 0, len(text), config.language))
    return tuple(result)


__all__ = ["split_text"]
