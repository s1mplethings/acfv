"""Unified Settings model bridging legacy ConfigManager and new arc pipeline.

This consolidates scattered config keys into a typed pydantic-style dataclass (without
introducing a hard dependency on pydantic for runtime) to keep footprint minimal.
If pydantic is available it will validate; otherwise a simple object is used.
"""
from __future__ import annotations

import os
import json
from typing import Optional, Dict, Any

try:
    from pydantic import BaseModel
    _HAVE_PYDANTIC = True
except ImportError:  # pragma: no cover
    _HAVE_PYDANTIC = False

DEFAULTS: Dict[str, Any] = {
    "VIDEO_FILE": "",
    "CHAT_FILE": "",
    "CHAT_OUTPUT": os.path.join("processing", "chat_with_emotes.json"),
    "ANALYSIS_OUTPUT": os.path.join("processing", "high_interest_segments.json"),
    "OUTPUT_CLIPS_DIR": os.path.join("processing", "output_clips"),
    "MAX_CLIP_COUNT": 10,
    "CHAT_DENSITY_WEIGHT": 0.3,
    "CHAT_SENTIMENT_WEIGHT": 0.4,
    "VIDEO_EMOTION_WEIGHT": 0.3,
    "SEGMENT_WINDOW": 20.0,
    "TOP_SEGMENTS": 10,
}

if _HAVE_PYDANTIC:
    class Settings(BaseModel):  # type: ignore[misc]
        video_file: str = DEFAULTS["VIDEO_FILE"]
        chat_file: Optional[str] = DEFAULTS["CHAT_FILE"] or None
        chat_output: str = DEFAULTS["CHAT_OUTPUT"]
        analysis_output: str = DEFAULTS["ANALYSIS_OUTPUT"]
        output_clips_dir: str = DEFAULTS["OUTPUT_CLIPS_DIR"]
        max_clip_count: int = DEFAULTS["MAX_CLIP_COUNT"]
        chat_density_weight: float = DEFAULTS["CHAT_DENSITY_WEIGHT"]
        chat_sentiment_weight: float = DEFAULTS["CHAT_SENTIMENT_WEIGHT"]
        video_emotion_weight: float = DEFAULTS["VIDEO_EMOTION_WEIGHT"]
        segment_window: float = DEFAULTS["SEGMENT_WINDOW"]
        top_segments: int = DEFAULTS["TOP_SEGMENTS"]

        @property
        def weights(self) -> Dict[str, float]:
            return {
                "CHAT_DENSITY_WEIGHT": self.chat_density_weight,
                "CHAT_SENTIMENT_WEIGHT": self.chat_sentiment_weight,
                "VIDEO_EMOTION_WEIGHT": self.video_emotion_weight,
            }

        def ensure_dirs(self) -> None:
            os.makedirs(os.path.dirname(self.chat_output), exist_ok=True)
            os.makedirs(os.path.dirname(self.analysis_output), exist_ok=True)
            os.makedirs(self.output_clips_dir, exist_ok=True)

else:
    class Settings:  # fallback simple container
        def __init__(self, **data: Any):
            merged = {**DEFAULTS, **data}
            self.video_file = merged["VIDEO_FILE"]
            self.chat_file = merged.get("CHAT_FILE") or None
            self.chat_output = merged["CHAT_OUTPUT"]
            self.analysis_output = merged["ANALYSIS_OUTPUT"]
            self.output_clips_dir = merged["OUTPUT_CLIPS_DIR"]
            self.max_clip_count = int(merged["MAX_CLIP_COUNT"])
            self.chat_density_weight = float(merged["CHAT_DENSITY_WEIGHT"])
            self.chat_sentiment_weight = float(merged["CHAT_SENTIMENT_WEIGHT"])
            self.video_emotion_weight = float(merged["VIDEO_EMOTION_WEIGHT"])
            self.segment_window = float(merged["SEGMENT_WINDOW"])
            self.top_segments = int(merged["TOP_SEGMENTS"])

        @property
        def weights(self) -> Dict[str, float]:
            return {
                "CHAT_DENSITY_WEIGHT": self.chat_density_weight,
                "CHAT_SENTIMENT_WEIGHT": self.chat_sentiment_weight,
                "VIDEO_EMOTION_WEIGHT": self.video_emotion_weight,
            }

        def ensure_dirs(self) -> None:
            os.makedirs(os.path.dirname(self.chat_output), exist_ok=True)
            os.makedirs(os.path.dirname(self.analysis_output), exist_ok=True)
            os.makedirs(self.output_clips_dir, exist_ok=True)

# ---- Loading / bridging helpers ----

_SETTINGS_SINGLETON: Optional[Settings] = None


def from_config_manager(cfg) -> Settings:
    """Create Settings from a legacy ConfigManager-like object (has get())."""
    data = {}
    for k in DEFAULTS.keys():
        if hasattr(cfg, "get"):
            v = cfg.get(k)
            if v is not None:
                data[k] = v
    settings = Settings(**data)  # type: ignore[arg-type]
    # fill video/chat file if provided under keys VIDEO_FILE / CHAT_FILE
    if hasattr(cfg, "get"):
        vf = cfg.get("VIDEO_FILE")
        cf = cfg.get("CHAT_FILE")
        if vf:
            settings.video_file = vf
        if cf:
            settings.chat_file = cf
    settings.ensure_dirs()
    return settings


def load_settings(path: Optional[str] = None, cfg=None) -> Settings:
    """Load settings from JSON/YAML or legacy config manager; path optional.

    Priority:
    1. Explicit path (json or yaml)
    2. Legacy cfg manager
    3. Defaults
    Caches singleton for subsequent calls.
    """
    global _SETTINGS_SINGLETON
    if _SETTINGS_SINGLETON is not None:
        return _SETTINGS_SINGLETON

    data: Dict[str, Any] = {}
    if path and os.path.isfile(path):
        try:
            if path.endswith(('.yaml', '.yml')):
                import yaml  # local import to avoid mandatory dep if not installed
                with open(path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
            elif path.endswith('.json'):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
        except Exception:
            data = {}
    elif cfg is not None:
        return from_config_manager(cfg)

    # Map potential alternative keys to canonical ones
    remap = {
        'chat_output': 'CHAT_OUTPUT',
        'analysis_output': 'ANALYSIS_OUTPUT',
        'output_clips_dir': 'OUTPUT_CLIPS_DIR',
        'segment_window': 'SEGMENT_WINDOW',
        'top_segments': 'TOP_SEGMENTS',
        'video_file': 'VIDEO_FILE',
        'chat_file': 'CHAT_FILE',
        'chat_density_weight': 'CHAT_DENSITY_WEIGHT',
        'chat_sentiment_weight': 'CHAT_SENTIMENT_WEIGHT',
        'video_emotion_weight': 'VIDEO_EMOTION_WEIGHT',
    }
    normalized: Dict[str, Any] = {}
    for k, v in data.items():
        key = remap.get(k, k)
        if key in DEFAULTS or key in ('VIDEO_FILE', 'CHAT_FILE'):
            normalized[key] = v

    _SETTINGS_SINGLETON = Settings(**normalized)  # type: ignore[arg-type]
    _SETTINGS_SINGLETON.ensure_dirs()
    return _SETTINGS_SINGLETON

__all__ = ["Settings", "load_settings", "from_config_manager"]
