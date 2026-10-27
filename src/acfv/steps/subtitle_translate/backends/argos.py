from __future__ import annotations

from typing import Dict, List

from .base import TranslatorBackend
from ..blockify import SubtitleBlock, SubtitleEvent


class ArgosBackend(TranslatorBackend):
    name = "argos"

    def __init__(self, source_lang: str = "en", target_lang: str = "zh"):
        self.source_lang = source_lang
        self.target_lang = target_lang
        try:
            from argostranslate import translate
        except Exception as exc:  # pragma: no cover - optional dependency
            raise ImportError("Argos Translate is not installed") from exc
        self._translate = translate

    def translate_block(self, block: SubtitleBlock) -> Dict[str, str]:
        return self.translate_lines(block.events)

    def translate_lines(self, events: List[SubtitleEvent]) -> Dict[str, str]:
        results: Dict[str, str] = {}
        for event in events:
            text = event.text
            if not text.strip():
                results[event.event_id] = ""
                continue
            translated = self._translate.translate(text, self.source_lang, self.target_lang)
            results[event.event_id] = translated
        return results


__all__ = ["ArgosBackend"]
