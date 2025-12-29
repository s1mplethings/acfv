from __future__ import annotations

from typing import Any, Dict, List

from acfv.modular.types import ModuleContext

CHAT_TYPE = "ChatLog:twitch_json.v1"
OUT_TYPE = "Segments:chat_spike.v1"


def run(ctx: ModuleContext) -> Dict[str, Any]:
    chat = ctx.inputs[CHAT_TYPE].payload or []
    window_sec = float(ctx.params.get("window_sec", 20.0))
    if window_sec <= 0:
        window_sec = 20.0
    top_n = int(ctx.params.get("top_n", 5))

    buckets: Dict[int, Dict[str, Any]] = {}
    for msg in chat:
        ts = msg.get("timestamp", msg.get("time", msg.get("t")))
        try:
            ts_val = float(ts)
        except Exception:
            continue
        idx = int(ts_val // window_sec)
        if idx not in buckets:
            start = idx * window_sec
            buckets[idx] = {"start": start, "end": start + window_sec, "count": 0}
        buckets[idx]["count"] += 1

    segments = [
        {"start": b["start"], "end": b["end"], "score": float(b["count"])}
        for b in buckets.values()
    ]
    segments.sort(key=lambda s: s["score"], reverse=True)
    if top_n > 0:
        segments = segments[:top_n]
    segments.sort(key=lambda s: s["start"])

    for seg in segments:
        seg["source"] = "chat_spike"

    return {OUT_TYPE: segments}


__all__ = ["run", "CHAT_TYPE", "OUT_TYPE"]
