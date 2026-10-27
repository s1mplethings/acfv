from __future__ import annotations

from typing import Iterable

from ..storage.models import Clip


def build_context(clips: Iterable[Clip], max_chars: int = 4000) -> str:
    """Simple concatenation of clip summaries for LLM prompting."""
    parts = []
    total = 0
    for clip in clips:
        summary = clip.summary_text or clip.raw_text or ""
        snippet = f"[{clip.clip_id}] {summary}".strip()
        if not snippet:
            continue
        if total + len(snippet) > max_chars:
            break
        parts.append(snippet)
        total += len(snippet)
    return "\n".join(parts)
