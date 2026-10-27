"""Immutable presentation models; they never query or mutate domain state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CreatorVM:
    id: str
    name: str
    platform: str
    recording_count: int
    live_state: str = "离线"
    processing_count: int = 0
    avatar_url: str = ""
    profile_status: str = "NOT_BUILT"
    profile_version: str = ""
    visual_status: str = "NOT_BUILT"
    adaptive_status: str = "SHADOW"
    voice_exemplars: int = 0
    trusted_speech_duration_ms: int = 0
    lexicon_entries: int = 0


@dataclass(frozen=True)
class RecordingVM:
    id: str
    creator_id: str
    title: str
    source_type: str
    date: str
    duration_ms: int
    language: str
    status: str
    media_path: str
    missing_media: bool
    error: str = ""
    media_revision: str = ""
    job_id: str = ""


@dataclass(frozen=True)
class MomentVM:
    id: str
    creator_id: str
    recording_id: str
    recording_title: str
    start_ms: int
    end_ms: int
    summary: str
    excerpt: str
    relevance: str = "相关"
    evidence: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ClipVM:
    id: str
    creator_id: str
    recording_id: str
    moment_id: str
    title: str
    start_ms: int
    end_ms: int
    render_status: str
    review_status: str
    output_path: str
    error: str = ""


@dataclass(frozen=True)
class VariantVM:
    profile: str
    status: str
    duration_ms: int = 0
    start_ms: int = 0
    end_ms: int = 0
    output_path: str = ""
    revision: int = 0
    warning_count: int = 0


@dataclass
class JobVM:
    id: str
    label: str
    context: str
    state: str = "排队中"
    progress: float | None = None
    elapsed_seconds: float = 0.0
    error: str = ""
    retryable: bool = False
    cancellable: bool = False


def duration_text(milliseconds: int) -> str:
    seconds = max(0, int(milliseconds)) // 1000
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def media_exists(path: str | None) -> bool:
    return bool(path and Path(path).is_file())
