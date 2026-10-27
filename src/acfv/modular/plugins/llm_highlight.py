from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from acfv import config as app_config
from acfv.modular.contracts import (
    ART_CHAT_LOG,
    ART_SCREEN_CONTEXT,
    ART_SEGMENTS,
    ART_SEGMENTS_LLM,
    ART_SEGMENTS_SEMANTIC,
    ART_TRANSCRIPT,
    ART_VIDEO_EMOTION,
)
from acfv.modular.types import ModuleContext, ModuleSpec
from acfv.steps.llm_highlight.impl import run_llm_highlight


def run(ctx: ModuleContext) -> Dict[str, Any]:
    work_dir = Path(ctx.store.run_dir) / "work"
    payload = run_llm_highlight(
        semantic_segments_payload=ctx.inputs[ART_SEGMENTS_SEMANTIC].payload if ART_SEGMENTS_SEMANTIC in ctx.inputs else {},
        candidate_segments_payload=ctx.inputs[ART_SEGMENTS].payload if ART_SEGMENTS in ctx.inputs else {},
        transcript_payload=ctx.inputs[ART_TRANSCRIPT].payload if ART_TRANSCRIPT in ctx.inputs else {},
        chat_payload=ctx.inputs[ART_CHAT_LOG].payload if ART_CHAT_LOG in ctx.inputs else {},
        screen_payload=ctx.inputs[ART_SCREEN_CONTEXT].payload if ART_SCREEN_CONTEXT in ctx.inputs else {},
        video_emotion_payload=ctx.inputs[ART_VIDEO_EMOTION].payload if ART_VIDEO_EMOTION in ctx.inputs else [],
        work_dir=work_dir,
        config_manager=getattr(app_config, "config_manager", None),
        enabled=ctx.params.get("enabled"),
        max_candidates_override=ctx.params.get("max_candidates"),
        target_segments_override=ctx.params.get("target_segments"),
        progress_callback=ctx.progress,
    )
    return {ART_SEGMENTS_LLM: payload}


spec = ModuleSpec(
    name="llm_highlight",
    version="1",
    inputs=[ART_SEGMENTS_SEMANTIC, ART_SEGMENTS, ART_TRANSCRIPT, ART_CHAT_LOG, ART_SCREEN_CONTEXT, ART_VIDEO_EMOTION],
    outputs=[ART_SEGMENTS_LLM],
    run=run,
    description="Use LLM to rerank semantic highlight candidates with transcript/chat/screen context.",
    impl_path="src/acfv/steps/llm_highlight/impl.py",
    default_params={"enabled": False, "max_candidates": 8, "target_segments": None},
)

__all__ = ["spec"]
