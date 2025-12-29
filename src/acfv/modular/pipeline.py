from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from acfv.modular.contracts import (
    ART_AUDIO_HOST,
    ART_CHAT_LOG,
    ART_CHAT_SOURCE,
    ART_CLIPS,
    ART_SEGMENTS,
    ART_TRANSCRIPT,
    ART_VIDEO,
    ART_VIDEO_EMOTION,
)
from acfv.modular.progress import ProgressEmitter
from acfv.modular.registry import AdapterRegistry, ModuleRegistry
from acfv.modular.runner import PipelineRunner
from acfv.modular.store import ArtifactStore
from acfv.modular.types import ProgressCallback

from acfv.modular.plugins.analyze_segments import spec as analyze_segments_spec
from acfv.modular.plugins.extract_audio import spec as extract_audio_spec
from acfv.modular.plugins.extract_chat import spec as extract_chat_spec
from acfv.modular.plugins.render_clips import spec as render_clips_spec
from acfv.modular.plugins.speaker_separation import spec as speaker_sep_spec
from acfv.modular.plugins.transcribe_audio import spec as transcribe_audio_spec
from acfv.modular.plugins.video_emotion import spec as video_emotion_spec


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


def _build_registries() -> tuple[ModuleRegistry, AdapterRegistry]:
    modules = ModuleRegistry()
    modules.register_many(
        [
            extract_chat_spec,
            extract_audio_spec,
            transcribe_audio_spec,
            video_emotion_spec,
            speaker_sep_spec,
            analyze_segments_spec,
            render_clips_spec,
        ]
    )
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
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("ACFV_DISABLE_PROGRESS_FILE", "1")
    store = ArtifactStore(run_dir)

    emitter = ProgressEmitter(store, run_id=run_dir.name, producer_name="pipeline")

    def _progress(stage: str, current: int, total: int, message: str = "") -> None:
        emitter.emit(stage, current, total, message)
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

    params_by_module = {
        "transcribe_audio": {
            "segment_length": _get_int(config_manager.get("SEGMENT_LENGTH") if config_manager else None, 300),
            "whisper_model": str(config_manager.get("WHISPER_MODEL") if config_manager else "medium"),
        },
        "video_emotion": {
            "enabled": _get_bool(config_manager.get("ENABLE_VIDEO_EMOTION") if config_manager else None, False),
            "segment_length": _get_float(config_manager.get("VIDEO_EMOTION_SEGMENT_LENGTH") if config_manager else None, 4.0),
            "model_path": str(config_manager.get("VIDEO_EMOTION_MODEL_PATH") if config_manager else ""),
            "device": config_manager.get("LLM_DEVICE") if config_manager else 0,
        },
        "speaker_separation": {
            "enabled": _get_bool(config_manager.get("ENABLE_SPEAKER_SEPARATION") if config_manager else None, False),
        },
        "analyze_segments": {
            "max_clips": max_clips,
            "video_emotion_weight": _get_float(config_manager.get("VIDEO_EMOTION_WEIGHT") if config_manager else None, 0.3),
            "enable_video_emotion": _get_bool(config_manager.get("ENABLE_VIDEO_EMOTION") if config_manager else None, False),
        },
        "render_clips": {
            "output_dir": output_clips_dir,
        },
    }

    results = runner.run(
        goal_types=[ART_CLIPS],
        seed_payloads=seed_payloads,
        params_by_module=params_by_module,
        progress_callback=_progress,
    )

    clips_payload = results.get(ART_CLIPS).payload if ART_CLIPS in results else []

    _progress("run", 1, 1, "done")

    return {
        "clips": clips_payload or [],
        "artifacts": results,
        "run_dir": str(run_dir),
    }


__all__ = ["run_pipeline"]
