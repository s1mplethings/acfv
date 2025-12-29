from __future__ import annotations

from typing import Any, Dict, List

from acfv.modular.types import ModuleContext

IN_TYPE = "Segments:chat_spike.v1"
OUT_TYPE = "Segments:unified.v1"


def run(ctx: ModuleContext) -> Dict[str, Any]:
    segments = ctx.inputs[IN_TYPE].payload or []
    min_score = float(ctx.params.get("min_score", 0.0))

    unified: List[Dict[str, Any]] = []
    for seg in segments:
        try:
            score = float(seg.get("score", 0.0))
        except Exception:
            score = 0.0
        if score < min_score:
            continue
        unified.append(
            {
                "start": float(seg.get("start", 0.0)),
                "end": float(seg.get("end", 0.0)),
                "score": score,
                "source": seg.get("source", "chat_spike"),
            }
        )

    unified.sort(key=lambda s: s["start"])
    return {OUT_TYPE: unified}


__all__ = ["run", "IN_TYPE", "OUT_TYPE"]
