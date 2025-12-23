"""Factory helpers for building each main window tab."""

from .base import TabHandle
from .clips_tab import create_clips_tab
from .local_tab import create_local_tab
from .twitch_tab import create_twitch_tab
from .rag_pref_tab import create_rag_pref_tab

__all__ = ["TabHandle", "create_twitch_tab", "create_local_tab", "create_clips_tab", "create_rag_pref_tab"]
