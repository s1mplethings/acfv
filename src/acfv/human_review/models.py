from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class ReviewTask(str, Enum):
    ASR = "asr"
    IDENTITY = "identity"
    TRUSTED_SPEECH = "trusted_speech"
    ADAPTIVE_ASR = "adaptive_asr"
    TRANSLATION = "translation"
    BOUNDARY = "boundary"
    WATCHABILITY = "watchability"
    SUBTITLE = "subtitle"
    PUBLISHABILITY = "publishability"


TASK_ORDER = (
    ReviewTask.ASR,
    ReviewTask.IDENTITY,
    ReviewTask.TRUSTED_SPEECH,
    ReviewTask.ADAPTIVE_ASR,
    ReviewTask.TRANSLATION,
    ReviewTask.BOUNDARY,
    ReviewTask.WATCHABILITY,
    ReviewTask.SUBTITLE,
    ReviewTask.PUBLISHABILITY,
)


@dataclass(frozen=True)
class ReviewSample:
    sample_id: str
    task: ReviewTask
    creator: str = ""
    content_type: str = ""
    title: str = ""
    media_a: str = ""
    media_b: str = ""
    start_ms: int = 0
    end_ms: int = 0
    prompt: Mapping[str, Any] = field(default_factory=dict)
    private: Mapping[str, Any] = field(default_factory=dict)
    source_path: str = ""
    consistency_control: bool = False

    def presentation(self, *, reveal: bool = False) -> dict[str, Any]:
        """Return UI-safe state. Provider/strategy identities stay private."""
        state = {
            "sample_id": self.sample_id,
            "task": self.task.value,
            "creator": self.creator,
            "content_type": self.content_type,
            "title": self.title,
            "media_a": self.media_a,
            "media_b": self.media_b,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "prompt": dict(self.prompt),
            "source_path": self.source_path,
            "consistency_control": self.consistency_control,
        }
        if reveal:
            state["reveal"] = dict(self.private)
        return state


@dataclass(frozen=True)
class TaskProgress:
    task: ReviewTask
    completed: int
    total: int
    skipped: int = 0
    revisit: int = 0


def coerce_task(value: str | ReviewTask) -> ReviewTask:
    return value if isinstance(value, ReviewTask) else ReviewTask(str(value).lower())
