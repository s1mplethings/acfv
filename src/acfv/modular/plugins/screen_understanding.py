from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from acfv import config as app_config
from acfv.modular.contracts import ART_SCREEN_CONTEXT, ART_SCREEN_WINDOWS, ART_TRANSCRIPT
from acfv.modular.types import ModuleContext, ModuleSpec
from acfv.steps.screen_understanding.impl import run_screen_understanding


def run(ctx: ModuleContext) -> Dict[str, Any]:
    screen_payload = ctx.inputs[ART_SCREEN_WINDOWS].payload if ART_SCREEN_WINDOWS in ctx.inputs else {}
    transcript_payload = ctx.inputs[ART_TRANSCRIPT].payload if ART_TRANSCRIPT in ctx.inputs else {}
    work_dir = Path(ctx.store.run_dir) / "work"
    payload = run_screen_understanding(
        screen_windows_payload=screen_payload,
        transcript_payload=transcript_payload,
        work_dir=work_dir,
        config_manager=getattr(app_config, "config_manager", None),
        enabled=ctx.params.get("enabled"),
        progress_callback=ctx.progress,
    )
    return {ART_SCREEN_CONTEXT: payload}


spec = ModuleSpec(
    name="screen_understanding",
    version="1",
    inputs=[ART_SCREEN_WINDOWS, ART_TRANSCRIPT],
    outputs=[ART_SCREEN_CONTEXT],
    run=run,
    description="Extract sparse keyframes and build structured desktop activity timeline.",
    impl_path="src/acfv/steps/screen_understanding/impl.py",
    default_params={"enabled": False},
)

__all__ = ["spec"]
