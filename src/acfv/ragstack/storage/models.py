from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Clip:
    clip_id: Optional[int]
    video_id: str
    start_sec: float
    end_sec: float
    duration: float
    summary_text: Optional[str] = None
    raw_text: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    highlight_score: Optional[float] = None
    emotion_score: Optional[float] = None
    talk_ratio: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None


@dataclass
class UserPreference:
    user_id: str
    tag_weights: Dict[str, float] = field(default_factory=dict)
    feature_prefs: Dict[str, Any] = field(default_factory=dict)
    pref_embedding: Optional[bytes] = None
    raw_preference_text: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class UserInteraction:
    user_id: str
    clip_id: int
    feedback_type: str  # "play","full_watch","like","dislike","skip","rewatch"
    watch_ratio: Optional[float] = None
