from __future__ import annotations

from typing import Any, Dict, List

from acfv.modular.types import ModuleContext, ModuleSpec

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


spec = ModuleSpec(
    name="merge_segments",
    version="0.1",
    inputs=[IN_TYPE],
    outputs=[OUT_TYPE],
    run=run,
    description="Normalize and filter segment candidates into unified schema.",
    impl_path="src/acfv/modular/plugins/merge_segments/module.py",
    default_params={"min_score": 0.0},
)

__all__ = ["spec"]
