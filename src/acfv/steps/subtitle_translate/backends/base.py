from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from ..blockify import SubtitleBlock, SubtitleEvent


@dataclass
class TranslationItem:
    event_id: str
    text: str


class TranslatorBackend:
    name = "base"

    def translate_block(self, block: SubtitleBlock) -> Dict[str, str]:
        raise NotImplementedError

    def translate_lines(self, events: List[SubtitleEvent]) -> Dict[str, str]:
        results: Dict[str, str] = {}
        for event in events:
            block = SubtitleBlock(events=[event])
            translated = self.translate_block(block)
            if event.event_id in translated:
                results[event.event_id] = translated[event.event_id]
        return results


__all__ = ["TranslationItem", "TranslatorBackend"]
