from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

from .config import provider_name, provider_settings

logger = logging.getLogger(__name__)


def resolve_scene_profile(config_manager: Any) -> dict[str, Any]:
    return provider_settings(
        config_manager,
        "scene",
        default_provider="pyscenedetect",
        legacy={
            "ENABLE_SCREEN_DETECT": "enabled",
            "SCREEN_DETECT_INTERVAL_SEC": "interval_sec",
            "SCREEN_MAX_FRAMES_PER_WINDOW": "max_frames_per_window",
            "SCREEN_DETECT_DEDUPE_HASH_DISTANCE": "dedupe_hash_distance",
        },
    )


def resolve_ocr_profile(config_manager: Any) -> dict[str, Any]:
    return provider_settings(
        config_manager,
        "ocr",
        default_provider="rapidvideocr",
        legacy={"SCREEN_ENABLE_OCR": "enabled"},
    )


def run_rapidvideocr(frame_path: Path) -> str:
    module_names = ("rapid_videocr", "RapidVideOCR")
    last_error: Exception | None = None
    for module_name in module_names:
        try:
            module = __import__(module_name, fromlist=["RapidVideOCR"])
        except Exception as exc:
            last_error = exc
            continue
        candidate = getattr(module, "RapidVideOCR", None) or getattr(module, "VideoOCR", None)
        if candidate is None:
            continue
        try:
            engine = candidate()
            if hasattr(engine, "run"):
                result = engine.run(str(frame_path))
            elif hasattr(engine, "ocr"):
                result = engine.ocr(str(frame_path))
            else:
                continue
            if isinstance(result, str):
                return " ".join(result.split())[:400]
            if isinstance(result, Iterable):
                texts = []
                for item in result:
                    if isinstance(item, str):
                        texts.append(item)
                    elif isinstance(item, dict) and item.get("text"):
                        texts.append(str(item["text"]))
                if texts:
                    return " ".join(" ".join(texts).split())[:400]
        except Exception as exc:
            last_error = exc
    if last_error:
        logger.info("[screen_detect] RapidVideOCR unavailable, fallback to pytesseract: %s", last_error)
    return ""


def scene_provider_name(config_manager: Any) -> str:
    return provider_name(config_manager, "scene", default="pyscenedetect")


def ocr_provider_name(config_manager: Any) -> str:
    return provider_name(config_manager, "ocr", default="rapidvideocr")


__all__ = [
    "ocr_provider_name",
    "resolve_ocr_profile",
    "resolve_scene_profile",
    "run_rapidvideocr",
    "scene_provider_name",
]
