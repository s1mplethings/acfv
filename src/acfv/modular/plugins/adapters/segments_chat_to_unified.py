from __future__ import annotations

from typing import Any, Dict, List

from acfv.modular.types import AdapterContext, AdapterSpec

SOURCE_TYPE = "Segments:chat_spike.v1"
TARGET_TYPE = "Segments:unified.v1"


def run(ctx: AdapterContext) -> Any:
    segments = ctx.source.payload or []
    unified: List[Dict[str, Any]] = []
    for seg in segments:
        unified.append(
            {
                "start": float(seg.get("start", 0.0)),
                "end": float(seg.get("end", 0.0)),
                "score": float(seg.get("score", 0.0)),
                "source": seg.get("source", "chat_spike"),
            }
        )
    unified.sort(key=lambda s: s["start"])
    return unified


spec = AdapterSpec(
    name="segments_chat_to_unified",
    version="0.1",
    source_type=SOURCE_TYPE,
    target_type=TARGET_TYPE,
    run=run,
    description="Convert chat spike segments to unified segment schema.",
)

__all__ = ["spec"]
