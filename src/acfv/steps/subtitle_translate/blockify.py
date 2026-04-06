from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class SubtitleEvent:
    event_id: str
    start_ms: int
    end_ms: int
    text: str
    index: int

    @property
    def duration_sec(self) -> float:
        return max(0.0, (self.end_ms - self.start_ms) / 1000.0)


@dataclass
class SubtitleBlock:
    events: List[SubtitleEvent]

    @property
    def ids(self) -> List[str]:
        return [event.event_id for event in self.events]

    @property
    def start_ms(self) -> int:
        return self.events[0].start_ms if self.events else 0

    @property
    def end_ms(self) -> int:
        return self.events[-1].end_ms if self.events else 0

    @property
    def duration_sec(self) -> float:
        return max(0.0, (self.end_ms - self.start_ms) / 1000.0)

    @property
    def char_count(self) -> int:
        return sum(len(event.text) for event in self.events)

    def block_text(self) -> str:
        return "\n".join(f"{event.event_id}|{event.text}" for event in self.events)


def build_blocks(
    events: List[SubtitleEvent],
    max_duration_sec: float = 10.0,
    max_chars: int = 350,
    max_gap_sec: float = 0.6,
    min_items: int = 2,
) -> List[SubtitleBlock]:
    if not events:
        return []

    blocks: List[SubtitleBlock] = []
    current: List[SubtitleEvent] = []

    def _flush() -> None:
        if current:
            blocks.append(SubtitleBlock(events=list(current)))
            current.clear()

    prev_event: SubtitleEvent | None = None
    for event in events:
        if not current:
            current.append(event)
            prev_event = event
            continue

        gap_sec = max(0.0, (event.start_ms - (prev_event.end_ms if prev_event else event.start_ms)) / 1000.0)
        would_duration = (event.end_ms - current[0].start_ms) / 1000.0
        would_chars = sum(len(e.text) for e in current) + len(event.text)

        if gap_sec <= max_gap_sec and would_duration <= max_duration_sec and would_chars <= max_chars:
            current.append(event)
        else:
            _flush()
            current.append(event)
        prev_event = event

    _flush()

    if min_items <= 1 or len(blocks) <= 1:
        return blocks

    merged: List[SubtitleBlock] = []
    for block in blocks:
        if len(block.events) >= min_items:
            merged.append(block)
            continue
        if merged:
            merged[-1].events.extend(block.events)
        else:
            merged.append(block)
    return merged


__all__ = ["SubtitleEvent", "SubtitleBlock", "build_blocks"]
