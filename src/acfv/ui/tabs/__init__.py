"""Factory helpers for building each main window tab."""

from .base import TabHandle
from .clips_tab import create_clips_tab
from .local_tab import create_local_tab
from .subtitle_render_tab import create_subtitle_render_tab
from .twitch_tab import create_twitch_tab


def create_rag_pref_tab(*args, **kwargs):
    """Lazy import RAG偏好面板，避免 GUI 冷启动时加载 torch 等重依赖。"""
    from .rag_pref_tab import create_rag_pref_tab as _impl
    return _impl(*args, **kwargs)


__all__ = [
    "TabHandle",
    "create_twitch_tab",
    "create_local_tab",
    "create_clips_tab",
    "create_subtitle_render_tab",
    "create_rag_pref_tab",
]
