from __future__ import annotations

from typing import Any, Dict

from acfv.modular.contracts import ART_SUBTITLES_STREAMER, ART_SUBTITLES_TRANSLATED
from acfv.modular.types import ModuleContext, ModuleSpec


def run(ctx: ModuleContext) -> Dict[str, Any]:
    enabled = bool(ctx.params.get("enabled", False))
    if not enabled:
        return {ART_SUBTITLES_TRANSLATED: {"status": "disabled"}}

    streamer_payload = ctx.inputs.get(ART_SUBTITLES_STREAMER)
    if streamer_payload and isinstance(streamer_payload.payload, dict):
        status = streamer_payload.payload.get("status")
        if status in {"disabled", "missing_source", "missing_primary_speaker", "unavailable"}:
            return {ART_SUBTITLES_TRANSLATED: {"status": status}}

    from acfv.steps.subtitle_translate import run_translate_streamer_subtitles

    result = run_translate_streamer_subtitles(
        run_dir=ctx.store.run_dir,
        config=ctx.params,
    )
    return {ART_SUBTITLES_TRANSLATED: result}


spec = ModuleSpec(
    name="subtitle_translate",
    version="1",
    inputs=[ART_SUBTITLES_STREAMER],
    outputs=[ART_SUBTITLES_TRANSLATED],
    run=run,
    description="Translate streamer subtitles with context blocks while keeping timeline stable.",
    impl_path="src/acfv/steps/subtitle_translate/step.py",
    default_params={
        "enabled": False,
        "engine": "llm_json",
        "target_lang": "zh-Hans",
        "source_lang": "en",
        "bilingual": False,
        "merge_mode": "lock_timeline",
        "block_max_duration": 10.0,
        "block_max_chars": 350,
        "block_max_gap": 0.6,
        "block_min_items": 2,
        "llm_api_url": "",
        "llm_api_key": "",
        "llm_model": "",
        "llm_system_prompt": "",
    },
)

__all__ = ["spec"]
