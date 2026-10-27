from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SearchScope(str, Enum):
    ENTIRE_LIBRARY = "ENTIRE_LIBRARY"
    CREATOR = "CREATOR"
    RECORDING = "RECORDING"
    LIVE_SESSION = "LIVE_SESSION"


@dataclass(frozen=True)
class SearchResult:
    moment_id: str
    creator_id: str
    recording_id: str
    start_ms: int
    end_ms: int
    score: float
    summary: str
    transcript_excerpt: str
    recording_title: str
    recorded_at: str | None
    moment_status: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)
