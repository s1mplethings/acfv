from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pysubs2

from .blockify import SubtitleEvent


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _to_ass_line(text: str) -> str:
    return _normalize_text(text).replace("\n", r"\N")


def write_translated(
    source_path: Path,
    events: List[SubtitleEvent],
    translations: Dict[str, str],
    output_path: Path,
    bilingual: bool = False,
) -> Path:
    subs = pysubs2.load(str(source_path))
    id_to_text = {event.event_id: translations.get(event.event_id, "") for event in events}

    for event in events:
        if event.index >= len(subs.events):
            continue
        translated = id_to_text.get(event.event_id, "")
        translated = _to_ass_line(translated)
        if bilingual:
            original = _to_ass_line(event.text)
            text = f"{original}\\N{translated}" if translated else original
        else:
            text = translated or _to_ass_line(event.text)
        subs.events[event.index].text = text

    output_path.parent.mkdir(parents=True, exist_ok=True)
    subs.save(str(output_path))
    return output_path


__all__ = ["write_translated"]
