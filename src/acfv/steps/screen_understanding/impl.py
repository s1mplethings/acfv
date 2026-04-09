from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from acfv.llm import JsonSchemaValidationError, get_default_client

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _normalize_windows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        items = payload.get("windows", [])
    else:
        items = payload or []
    out: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        start = _safe_float(item.get("start"), 0.0)
        end = _safe_float(item.get("end"), 0.0)
        if end <= start:
            continue
        out.append(item)
    return out


def _normalize_transcript(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        segments = payload.get("segments", [])
    else:
        segments = payload or []
    out: List[Dict[str, Any]] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        start = _safe_float(seg.get("start"), 0.0)
        end = _safe_float(seg.get("end"), 0.0)
        text = str(seg.get("text") or "").strip()
        if end <= start:
            continue
        out.append({"start": start, "end": end, "text": text})
    return out


def _transcript_hint(segments: Iterable[Dict[str, Any]], start: float, end: float, limit_chars: int = 240) -> str:
    texts: List[str] = []
    for seg in segments:
        overlap = max(0.0, min(end, _safe_float(seg.get("end"))) - max(start, _safe_float(seg.get("start"))))
        if overlap <= 0:
            continue
        text = str(seg.get("text") or "").strip()
        if text:
            texts.append(text)
        if sum(len(t) for t in texts) >= limit_chars:
            break
    return " ".join(texts)[:limit_chars]


def _heuristic_context(ocr_text: str, transcript_hint: str) -> Dict[str, Any]:
    combined = f"{ocr_text}\n{transcript_hint}".lower()
    mapping = [
        ("code_editor", "VS Code", "reading and editing code", ["code", "python", ".py", "vscode", "class ", "def "]),
        ("terminal", "Terminal", "running terminal commands", ["powershell", "cmd", "bash", "python ", "git "]),
        ("github", "GitHub", "reading commits or pull requests", ["github", "pull request", "commit", "compare"]),
        ("browser_docs", "Browser", "reading documentation", ["docs", "documentation", "readme", "api reference"]),
        ("game", "Game", "gameplay or results screen", ["victory", "defeat", "score", "round", "leaderboard"]),
    ]
    for screen_type, app, activity, words in mapping:
        if any(word in combined for word in words):
            return {
                "screen_type": screen_type,
                "app_guess": app,
                "activity": activity,
                "entities": [],
                "summary": activity,
                "confidence": 0.35,
            }
    return {
        "screen_type": "unknown",
        "app_guess": "",
        "activity": "screen activity unclear",
        "entities": [],
        "summary": "无法稳定判断电脑画面在做什么",
        "confidence": 0.15,
    }


def _schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "screen_type": {"type": "string"},
            "app_guess": {"type": "string"},
            "activity": {"type": "string"},
            "entities": {"type": "array", "items": {"type": "string"}},
            "summary": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": ["screen_type", "activity", "summary", "confidence"],
        "additionalProperties": True,
    }


def _validate_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    entities = payload.get("entities")
    if entities is None:
        entities = []
    if not isinstance(entities, list):
        raise JsonSchemaValidationError("entities must be list")
    payload["screen_type"] = str(payload.get("screen_type") or "").strip()
    payload["app_guess"] = str(payload.get("app_guess") or "").strip()
    payload["activity"] = str(payload.get("activity") or "").strip()
    payload["entities"] = [str(item).strip() for item in entities if str(item).strip()]
    payload["summary"] = str(payload.get("summary") or "").strip()
    payload["confidence"] = max(0.0, min(1.0, _safe_float(payload.get("confidence"), 0.0)))
    if not payload["screen_type"] or not payload["activity"] or not payload["summary"]:
        raise JsonSchemaValidationError("screen understanding fields missing")
    return payload


def _describe_window(
    *,
    frame_path: Path,
    ocr_text: str,
    transcript_hint: str,
    config_manager: Any,
) -> Optional[Dict[str, Any]]:
    vision_model = ""
    if config_manager is not None:
        try:
            vision_model = str(config_manager.get("LLM_VISION_MODEL", "") or config_manager.get("SCREEN_UNDERSTANDING_MODEL", "") or "")
        except Exception:
            vision_model = ""
    client = get_default_client(config_manager=config_manager, model=vision_model or None, prefix="LLM")
    if not client.available:
        return None
    image_b64 = base64.b64encode(frame_path.read_bytes()).decode("ascii")
    system_prompt = (
        "You analyze desktop capture frames. Return only JSON with screen_type, app_guess, activity, entities, summary, confidence."
    )
    user_prompt = (
        "Infer what the computer screen is and what the user is doing.\n"
        f"OCR hint: {ocr_text or '[none]'}\n"
        f"Transcript hint: {transcript_hint or '[none]'}\n"
        "Keep entities short and concrete."
    )
    try:
        return client.complete_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            images=[{"mime_type": "image/jpeg", "data_base64": image_b64}],
            validator=_validate_payload,
            schema=_schema(),
            temperature=0.0,
        )
    except Exception as exc:
        logger.warning("[screen_understanding] llm vision failed: %s", exc)
        return None


def run_screen_understanding(
    *,
    screen_windows_payload: Any,
    transcript_payload: Any,
    work_dir: Path,
    config_manager: Any = None,
    enabled: Optional[bool] = None,
    progress_callback=None,
) -> Dict[str, Any]:
    require_api = False
    if enabled is None and config_manager is not None:
        try:
            enabled = bool(config_manager.get("ENABLE_SCREEN_UNDERSTANDING", False))
            require_api = bool(config_manager.get("REQUIRE_LLM_API", False))
        except Exception:
            enabled = False
            require_api = False
    if enabled is None:
        enabled = False
    if not enabled:
        return {"schema_version": SCHEMA_VERSION, "status": "disabled", "timeline": []}

    windows = _normalize_windows(screen_windows_payload)
    transcript_segments = _normalize_transcript(transcript_payload)
    if not windows:
        return {"schema_version": SCHEMA_VERSION, "status": "no_windows", "timeline": []}

    work_dir.mkdir(parents=True, exist_ok=True)
    timeline: List[Dict[str, Any]] = []
    total = max(1, len(windows))
    for idx, window in enumerate(windows):
        if progress_callback:
            progress_callback("screen_understanding", idx, total, f"window {idx + 1}/{total}")
        start = _safe_float(window.get("start"), 0.0)
        end = _safe_float(window.get("end"), 0.0)
        frame_paths = window.get("frame_paths") or []
        frame_path = Path(frame_paths[0]) if frame_paths else None
        ocr_text = str(window.get("ocr_text_hint") or "").strip()
        transcript_hint = _transcript_hint(transcript_segments, start, end)

        llm_payload = None
        if frame_path is not None and frame_path.exists():
            llm_payload = _describe_window(
                frame_path=frame_path,
                ocr_text=ocr_text,
                transcript_hint=transcript_hint,
                config_manager=config_manager,
            )

        if llm_payload is None and require_api:
            raise RuntimeError(
                "screen_understanding requires API LLM/VLM, but no usable API response was produced. "
                "Set LLM_API_KEY/OPENAI_API_KEY and ensure LLM_VISION_MODEL or compatible base_url is available."
            )

        if llm_payload is None:
            llm_payload = _heuristic_context(ocr_text, transcript_hint)

        timeline.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "screen_type": llm_payload.get("screen_type", "unknown"),
                "app_guess": llm_payload.get("app_guess", ""),
                "activity": llm_payload.get("activity", ""),
                "entities": llm_payload.get("entities", []),
                "summary": llm_payload.get("summary", ""),
                "confidence": llm_payload.get("confidence", 0.0),
                "screen_bbox": window.get("screen_bbox"),
                "is_fullscreen_capture": bool(window.get("is_fullscreen_capture", False)),
                "ocr_text_hint": ocr_text,
                "frame_paths": frame_paths,
            }
        )

    payload = {"schema_version": SCHEMA_VERSION, "status": "ok", "timeline": timeline}
    (work_dir / "screen_context.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if progress_callback:
        progress_callback("screen_understanding", total, total, "done")
    return payload


__all__ = ["run_screen_understanding"]
