from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _average_hash(frame) -> str:
    import cv2
    import numpy as np

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA)
    mean = float(np.mean(small))
    bits = ["1" if float(value) >= mean else "0" for value in small.flatten()]
    return "".join(bits)


def _hash_distance(a: str, b: str) -> int:
    if not a or not b or len(a) != len(b):
        return 64
    return sum(ch1 != ch2 for ch1, ch2 in zip(a, b))


def _extract_ocr(frame) -> str:
    try:
        import cv2
        import pytesseract
    except Exception:
        return ""
    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        text = pytesseract.image_to_string(gray)
        return " ".join(text.split())[:400]
    except Exception:
        return ""


def _detect_screen_bbox(frame) -> Tuple[List[int], bool, float]:
    import cv2
    import numpy as np

    h, w = frame.shape[:2]
    full = [0, 0, int(w), int(h)]

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 180)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80, minLineLength=min(w, h) // 4, maxLineGap=12)

    rect_like = 0
    if lines is not None:
        for line in lines[:100]:
            x1, y1, x2, y2 = line[0]
            if abs(x2 - x1) > abs(y2 - y1):
                rect_like += 1
            else:
                rect_like += 1

    text_density = float(np.count_nonzero(edges)) / max(1.0, float(w * h))
    if text_density > 0.015 or rect_like > 18:
        return full, True, 0.75

    center_x1 = int(w * 0.1)
    center_x2 = int(w * 0.9)
    center_y1 = int(h * 0.08)
    center_y2 = int(h * 0.92)
    return [center_x1, center_y1, center_x2, center_y2], False, 0.45


def run_screen_detect(
    *,
    video_path: str,
    work_dir: Path,
    config_manager: Any = None,
    enabled: Optional[bool] = None,
    interval_sec: Optional[float] = None,
    max_frames_per_window: Optional[int] = None,
    enable_ocr: Optional[bool] = None,
    dedupe_hash_distance: Optional[int] = None,
    progress_callback=None,
) -> Dict[str, Any]:
    try:
        import cv2
    except Exception:
        return {"schema_version": SCHEMA_VERSION, "status": "cv2_unavailable", "windows": [], "frames": []}

    if enabled is None and config_manager is not None:
        try:
            enabled = bool(config_manager.get("ENABLE_SCREEN_DETECT", False))
        except Exception:
            enabled = False
    if enabled is None:
        enabled = False
    if not enabled:
        return {"schema_version": SCHEMA_VERSION, "status": "disabled", "windows": [], "frames": []}

    frame_interval = max(5.0, _safe_float(interval_sec, 30.0))
    max_windows = max(1, int(max_frames_per_window or 12))
    dedupe_distance = max(0, int(dedupe_hash_distance or 6))
    ocr_enabled = bool(True if enable_ocr is None else enable_ocr)
    if config_manager is not None:
        try:
            frame_interval = max(
                5.0, _safe_float(config_manager.get("SCREEN_DETECT_INTERVAL_SEC", frame_interval), frame_interval)
            )
            max_windows = max(
                1, int(config_manager.get("SCREEN_MAX_FRAMES_PER_WINDOW", max_windows) or max_windows)
            )
            dedupe_distance = max(
                0, int(config_manager.get("SCREEN_DETECT_DEDUPE_HASH_DISTANCE", dedupe_distance) or dedupe_distance)
            )
            ocr_enabled = bool(config_manager.get("SCREEN_ENABLE_OCR", ocr_enabled))
        except Exception:
            pass

    work_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = work_dir / "screen_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {"schema_version": SCHEMA_VERSION, "status": "video_open_failed", "windows": [], "frames": []}

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or 25.0
    frame_count = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
    duration = frame_count / fps if frame_count > 0 else 0.0

    timestamps: List[float] = []
    if duration > 0:
        current = 0.0
        while current < duration and len(timestamps) < max_windows:
            timestamps.append(round(current, 3))
            current += frame_interval
        if len(timestamps) < max_windows and (not timestamps or abs(duration - timestamps[-1]) > 2.0):
            timestamps.append(round(max(0.0, duration - min(frame_interval, duration)), 3))

    frames: List[Dict[str, Any]] = []
    windows: List[Dict[str, Any]] = []
    last_hash = ""
    total = max(1, len(timestamps))
    for idx, ts in enumerate(timestamps):
        if progress_callback:
            progress_callback("screen_detect", idx, total, f"frame {idx + 1}/{total}")
        cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        frame_hash = _average_hash(frame)
        if last_hash and _hash_distance(last_hash, frame_hash) <= dedupe_distance:
            continue
        last_hash = frame_hash

        bbox, is_fullscreen, confidence = _detect_screen_bbox(frame)
        ocr_text = _extract_ocr(frame) if ocr_enabled else ""
        frame_path = frames_dir / f"detect_{idx + 1:03d}_{int(round(ts * 1000)):08d}.jpg"
        cv2.imwrite(str(frame_path), frame)
        frame_record = {
            "timestamp_sec": ts,
            "frame_path": str(frame_path),
            "screen_bbox": bbox,
            "is_fullscreen_capture": is_fullscreen,
            "ocr_text_hint": ocr_text,
            "confidence": round(confidence, 3),
            "hash": frame_hash,
        }
        frames.append(frame_record)
        next_ts = timestamps[idx + 1] if idx + 1 < len(timestamps) else min(duration, ts + frame_interval) if duration > 0 else ts + frame_interval
        windows.append(
            {
                "start": round(ts, 3),
                "end": round(max(next_ts, ts + 1.0), 3),
                "frame_paths": [str(frame_path)],
                "screen_bbox": bbox,
                "is_fullscreen_capture": is_fullscreen,
                "ocr_text_hint": ocr_text,
                "confidence": round(confidence, 3),
            }
        )

    cap.release()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "duration_sec": round(duration, 3) if duration else 0.0,
        "windows": windows,
        "frames": frames,
    }
    (work_dir / "screen_detect.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if progress_callback:
        progress_callback("screen_detect", total, total, "done")
    return payload


__all__ = ["run_screen_detect"]
