from __future__ import annotations

import os
import importlib
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from acfv import config as app_config
from acfv.modular.contracts import (
    ART_AUDIO_HOST,
    ART_CHAT_LOG,
    ART_CHAT_SOURCE,
    ART_CLIPS,
    ART_SCREEN_CONTEXT,
    ART_SCREEN_FRAMES,
    ART_SCREEN_WINDOWS,
    ART_SEGMENTS,
    ART_SEGMENTS_LLM,
    ART_TRANSCRIPT,
    ART_VIDEO,
    ART_VIDEO_EMOTION,
)
from acfv.modular.progress import ProgressEmitter
from acfv.modular.registry import AdapterRegistry, ModuleRegistry
from acfv.modular.runner import PipelineRunner
from acfv.modular.store import ArtifactStore
from acfv.modular.types import ProgressCallback

logger = logging.getLogger(__name__)

def _get_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return default


def _get_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _get_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _load_plugin_specs() -> list:
    """Lazily import plugin specs to avoid heavy dependencies at import time."""
    plugin_modules = [
        "acfv.modular.plugins.extract_chat",
        "acfv.modular.plugins.extract_audio",
        "acfv.modular.plugins.transcribe_audio",
        "acfv.modular.plugins.screen_detect",
        "acfv.modular.plugins.screen_understanding",
        "acfv.modular.plugins.video_emotion",
        "acfv.modular.plugins.speaker_separation",
        "acfv.modular.plugins.streamer_subtitles",
        "acfv.modular.plugins.subtitle_translate",
        "acfv.modular.plugins.analyze_segments",
        "acfv.modular.plugins.semantic_merge",
        "acfv.modular.plugins.llm_highlight",
        "acfv.modular.plugins.render_clips",
    ]
    specs = []
    for module_path in plugin_modules:
        try:
            module = importlib.import_module(module_path)
            spec = getattr(module, "spec", None)
            if spec:
                specs.append(spec)
            else:
                logger.warning("Plugin %s missing spec attribute; skipping", module_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to import plugin %s: %s", module_path, exc)
    return specs


def _build_registries() -> tuple[ModuleRegistry, AdapterRegistry]:
    modules = ModuleRegistry()
    modules.register_many(_load_plugin_specs())
    adapters = AdapterRegistry()
    return modules, adapters


def run_pipeline(
    video_path: str,
    chat_path: Optional[str],
    config_manager: Any,
    run_dir: Path,
    output_clips_dir: Optional[str] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    logger.info(
        "[pipeline] start run_dir=%s video=%s chat=%s output_dir=%s",
        run_dir,
        video_path,
        chat_path,
        output_clips_dir or "<default>",
    )
    if config_manager is not None:
        # Modular plugins still consult the global config object; mirror the
        # caller-supplied config source so CLI YAML overrides are actually used.
        app_config.config_manager = config_manager
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("ACFV_DISABLE_PROGRESS_FILE", "1")
    store = ArtifactStore(run_dir)

    emitter = ProgressEmitter(store, run_id=run_dir.name, producer_name="pipeline")

    def _progress(stage: str, current: int, total: int, message: str = "") -> None:
        emitter.emit(stage, current, total, message)
        logger.info("[progress] %s %s/%s %s", stage, current, total, message or "")
        if progress_callback:
            progress_callback(stage, current, total, message)

    _progress("run", 0, 1, "start")

    modules, adapters = _build_registries()
    runner = PipelineRunner(modules, adapters, store)

    seed_payloads: Dict[str, Any] = {
        ART_VIDEO: {"path": video_path},
    }
    if chat_path and os.path.exists(chat_path):
        seed_payloads[ART_CHAT_SOURCE] = {"path": chat_path}
    else:
        seed_payloads[ART_CHAT_LOG] = []

    max_clips = _get_int(config_manager.get("MAX_CLIP_COUNT") if config_manager else None, 0)
    max_clips = max_clips if max_clips > 0 else None
    llm_candidate_multiplier = _get_int(
        config_manager.get("LLM_HIGHLIGHT_CANDIDATE_MULTIPLIER") if config_manager else None,
        5,
    )
    if llm_candidate_multiplier <= 0:
        llm_candidate_multiplier = 5
    rough_candidate_count = max_clips * llm_candidate_multiplier if max_clips else None

    min_seg_duration = _get_float(config_manager.get("MIN_CLIP_SEGMENT_SECONDS") if config_manager else None, 6.0)
    if config_manager and config_manager.get("MIN_CLIP_SEGMENT_SECONDS") is None:
        min_seg_duration = _get_float(config_manager.get("MIN_INTEREST_SEGMENT_DURATION"), min_seg_duration)
    enable_enhance = _get_bool(config_manager.get("ENABLE_ENHANCE") if config_manager else None, False)
    enable_asr = _get_bool(config_manager.get("ENHANCE_ASR") if config_manager else None, True)
    subtitle_enabled = enable_enhance and enable_asr
    enable_streamer_subtitles = _get_bool(
        config_manager.get("ENABLE_STREAMER_SUBTITLES") if config_manager else None, False
    )
    enable_subtitle_translate = _get_bool(
        config_manager.get("ENABLE_SUBTITLE_TRANSLATE") if config_manager else None, False
    )
    primary_speaker = None
    if config_manager:
        primary_speaker = config_manager.get("STREAMER_PRIMARY_SPEAKER")
    language_value = config_manager.get("TRANSCRIPTION_LANGUAGE") if config_manager else ""
    language_cfg = str(language_value or "").strip().lower()
    language = None if language_cfg in {"", "auto", "detect", "default"} else language_cfg

    params_by_module = {
        "transcribe_audio": {
            "segment_length": _get_int(config_manager.get("SEGMENT_LENGTH") if config_manager else None, 300),
            "whisper_model": str(config_manager.get("WHISPER_MODEL") if config_manager else "medium"),
            "whisper_engine": str(config_manager.get("WHISPER_ENGINE") if config_manager else "auto"),
            "hf_whisper_model": str(config_manager.get("HF_WHISPER_MODEL") if config_manager else "openai/whisper-medium"),
            "language": language,
        },
        "video_emotion": {
            "enabled": _get_bool(config_manager.get("ENABLE_VIDEO_EMOTION") if config_manager else None, False),
            "segment_length": _get_float(config_manager.get("VIDEO_EMOTION_SEGMENT_LENGTH") if config_manager else None, 4.0),
            "model_path": str(config_manager.get("VIDEO_EMOTION_MODEL_PATH") if config_manager else ""),
            "device": config_manager.get("LLM_DEVICE") if config_manager else 0,
        },
        "screen_detect": {
            "enabled": _get_bool(config_manager.get("ENABLE_SCREEN_DETECT") if config_manager else None, False),
            "interval_sec": _get_float(config_manager.get("SCREEN_DETECT_INTERVAL_SEC") if config_manager else None, 30.0),
            "max_frames_per_window": _get_int(
                config_manager.get("SCREEN_MAX_FRAMES_PER_WINDOW") if config_manager else None, 12
            ),
            "enable_ocr": _get_bool(config_manager.get("SCREEN_ENABLE_OCR") if config_manager else None, True),
            "dedupe_hash_distance": _get_int(
                config_manager.get("SCREEN_DETECT_DEDUPE_HASH_DISTANCE") if config_manager else None, 6
            ),
        },
        "screen_understanding": {
            "enabled": _get_bool(config_manager.get("ENABLE_SCREEN_UNDERSTANDING") if config_manager else None, False),
        },
        "speaker_separation": {
            "enabled": _get_bool(config_manager.get("ENABLE_SPEAKER_SEPARATION") if config_manager else None, False),
        },
        "streamer_subtitles": {
            "enabled": enable_streamer_subtitles,
            "primary_speaker": primary_speaker,
        },
        "subtitle_translate": {
            "enabled": enable_subtitle_translate,
            "engine": config_manager.get("SUBTITLE_TRANSLATE_ENGINE") if config_manager else "llm_json",
            "target_lang": config_manager.get("SUBTITLE_TRANSLATE_TARGET_LANG") if config_manager else "zh-Hans",
            "source_lang": config_manager.get("SUBTITLE_TRANSLATE_SOURCE_LANG") if config_manager else "en",
            "bilingual": _get_bool(config_manager.get("SUBTITLE_TRANSLATE_BILINGUAL") if config_manager else None, False),
            "merge_mode": config_manager.get("SUBTITLE_TRANSLATE_MERGE_MODE") if config_manager else "lock_timeline",
            "block_max_duration": _get_float(
                config_manager.get("SUBTITLE_TRANSLATE_BLOCK_MAX_DURATION") if config_manager else None, 10.0
            ),
            "block_max_chars": _get_int(
                config_manager.get("SUBTITLE_TRANSLATE_BLOCK_MAX_CHARS") if config_manager else None, 350
            ),
            "block_max_gap": _get_float(
                config_manager.get("SUBTITLE_TRANSLATE_BLOCK_MAX_GAP") if config_manager else None, 0.6
            ),
            "block_min_items": _get_int(
                config_manager.get("SUBTITLE_TRANSLATE_BLOCK_MIN_ITEMS") if config_manager else None, 2
            ),
            "llm_api_url": config_manager.get("SUBTITLE_TRANSLATE_LLM_API_URL") if config_manager else "",
            "llm_api_key": config_manager.get("SUBTITLE_TRANSLATE_LLM_API_KEY") if config_manager else "",
            "llm_model": config_manager.get("SUBTITLE_TRANSLATE_LLM_MODEL") if config_manager else "",
            "llm_system_prompt": config_manager.get("SUBTITLE_TRANSLATE_LLM_SYSTEM_PROMPT") if config_manager else "",
        },
        "analyze_segments": {
            "max_clips": rough_candidate_count,
            "video_emotion_weight": _get_float(config_manager.get("VIDEO_EMOTION_WEIGHT") if config_manager else None, 0.3),
            "enable_video_emotion": _get_bool(config_manager.get("ENABLE_VIDEO_EMOTION") if config_manager else None, False),
            "min_duration_sec": min_seg_duration,
        },
        "render_clips": {
            "output_dir": output_clips_dir,
            "subtitle_enabled": subtitle_enabled,
            "subtitle_format": str(config_manager.get("SUBTITLE_FORMAT") if config_manager else "srt") or "srt",
        },
        "llm_highlight": {
            "enabled": _get_bool(config_manager.get("ENABLE_LLM_HIGHLIGHT") if config_manager else None, False),
            "max_candidates": _get_int(
                config_manager.get("LLM_HIGHLIGHT_MAX_CANDIDATES") if config_manager else None,
                rough_candidate_count or 8,
            ),
            "target_segments": max_clips,
        },
    }

    results = runner.run(
        goal_types=[ART_CLIPS],
        seed_payloads=seed_payloads,
        params_by_module=params_by_module,
        progress_callback=_progress,
    )

    clips_payload = results.get(ART_CLIPS).payload if ART_CLIPS in results else []

    clips_list: list = []
    subtitles: list = []
    merge_gap = None
    max_merge = None
    segments_out = None
    manifest_path = None
    thumbnails = []
    screen_context_path = None
    llm_segments_path = None
    if isinstance(clips_payload, dict):
        clips_list = clips_payload.get("clips") or []
        subtitles = clips_payload.get("subtitles") or []
        merge_gap = clips_payload.get("merge_gap_sec")
        max_merge = clips_payload.get("max_merged_duration")
        segments_out = clips_payload.get("segments")
        thumbnails = clips_payload.get("thumbnails") or []
        manifest_path = clips_payload.get("manifest_path")
    elif isinstance(clips_payload, list):
        clips_list = clips_payload

    screen_context_env = results.get(ART_SCREEN_CONTEXT)
    if screen_context_env is not None:
        screen_context_path = str((Path(run_dir) / "work" / "screen_context.json"))
    llm_segments_env = results.get(ART_SEGMENTS_LLM)
    if llm_segments_env is not None:
        llm_segments_path = str((Path(run_dir) / "work" / "segments_llm.json"))

    _progress("run", 1, 1, "done")
    logger.info("[pipeline] run finished; clips=%d", len(clips_list))

    work_dir = Path(run_dir) / "work"
    segments_path = work_dir / "segments.json"
    chat_json_path = work_dir / "chat.json"
    manifest_json_path = work_dir / "clips_manifest.json"
    if not manifest_path and manifest_json_path.exists():
        manifest_path = manifest_json_path
    logger.info(
        "[pipeline] artifacts segments=%s chat=%s manifest=%s",
        segments_path if segments_path.exists() else None,
        chat_json_path if chat_json_path.exists() else None,
        manifest_path,
    )

    contract_output = {
        "schema_version": "1.0.0",
        "clips": [str(c) for c in clips_list],
        "subtitles": [str(s) for s in subtitles],
        "segments_json": str(segments_path) if segments_path.exists() else None,
        "chat_json": str(chat_json_path) if chat_json_path.exists() else None,
        "clips_manifest_json": str(manifest_path) if manifest_path else None,
        "thumbnails": [str(t) for t in thumbnails],
        "logs": [],
        "run_dir": str(run_dir),
        "merge_gap_sec": merge_gap,
        "max_merged_duration": max_merge,
        "screen_context_json": screen_context_path,
        "segments_llm_json": llm_segments_path,
    }
    if segments_out:
        contract_output["segments"] = segments_out

    return {
        "clips": clips_list,
        "artifacts": results,
        "run_dir": str(run_dir),
        "contract_output": contract_output,
    }


__all__ = ["run_pipeline"]
