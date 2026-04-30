"""TTS backends and A/B comparison helpers."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict

import requests


class TTSError(RuntimeError):
    """Raised when TTS generation fails."""


def _normalize_prosody(value: Any, *, fallback: str = "+0%") -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    if text.endswith("%"):
        return text
    try:
        return f"{int(float(text)):+d}%"
    except ValueError:
        return fallback


def _normalize_pitch(value: Any, *, fallback: str = "+0Hz") -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    if text.endswith("Hz"):
        return text
    if text.endswith("%"):
        text = text[:-1]
    try:
        return f"{int(float(text)):+d}Hz"
    except ValueError:
        return fallback


def _speech_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/audio/speech"


def _write_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _run_coro(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def synthesize_edge_tts(
    text: str,
    output_path: Path,
    *,
    voice: str,
    rate: str,
    pitch: str,
) -> Path:
    try:
        import edge_tts  # type: ignore
    except ImportError as exc:
        raise TTSError("edge-tts 未安装，请执行: pip install edge-tts") from exc
    if not text.strip():
        raise TTSError("输入文本为空，无法生成语音")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    communicator = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=_normalize_prosody(rate),
        pitch=_normalize_pitch(pitch),
    )
    _run_coro(communicator.save(str(output_path)))
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise TTSError("edge-tts 未生成有效音频文件")
    return output_path


def synthesize_openai_compatible(
    text: str,
    output_path: Path,
    *,
    base_url: str,
    api_key: str,
    model: str,
    voice: str,
    response_format: str,
    timeout_sec: int,
) -> Path:
    if not text.strip():
        raise TTSError("输入文本为空，无法生成语音")
    if not base_url.strip():
        raise TTSError("VibeVoice base_url 为空")
    if not model.strip():
        raise TTSError("VibeVoice model 为空")

    headers = {"Content-Type": "application/json"}
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    payload = {
        "model": model.strip(),
        "input": text,
        "voice": voice.strip(),
        "response_format": response_format.strip() or "mp3",
    }
    try:
        resp = requests.post(
            _speech_url(base_url),
            headers=headers,
            json=payload,
            timeout=timeout_sec,
        )
    except requests.RequestException as exc:
        raise TTSError(f"请求 VibeVoice 失败: {exc}") from exc
    if resp.status_code >= 400:
        body = resp.text[:300].strip()
        raise TTSError(f"VibeVoice 接口错误 HTTP {resp.status_code}: {body}")
    if not resp.content:
        raise TTSError("VibeVoice 返回空音频")
    return _write_bytes(output_path, resp.content)


def compare_tts(
    *,
    text: str,
    out_dir: Path,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = int(time.time())

    current_voice = str(config.get("TTS_CURRENT_VOICE", "zh-CN-XiaoxiaoNeural"))
    current_rate = str(config.get("TTS_CURRENT_RATE", "+0%"))
    current_pitch = str(config.get("TTS_CURRENT_PITCH", "+0%"))
    current_out = out_dir / f"tts_current_edge_{stamp}.mp3"

    vibe_base_url = str(config.get("TTS_VIBEVOICE_BASE_URL", "http://127.0.0.1:8000/v1"))
    vibe_api_key = str(config.get("TTS_VIBEVOICE_API_KEY", "local"))
    vibe_model = str(config.get("TTS_VIBEVOICE_MODEL", "vibevoice"))
    vibe_voice = str(config.get("TTS_VIBEVOICE_VOICE", "alloy"))
    vibe_format = str(config.get("TTS_VIBEVOICE_FORMAT", "mp3")).lower()
    vibe_timeout = int(config.get("TTS_VIBEVOICE_TIMEOUT_SEC", 60) or 60)
    vibe_out = out_dir / f"tts_vibevoice_{stamp}.{vibe_format}"

    result: Dict[str, Any] = {
        "text_chars": len(text),
        "out_dir": str(out_dir),
        "current": {"backend": "edge-tts", "ok": False},
        "vibevoice": {"backend": "openai-compatible", "ok": False},
    }

    t0 = time.perf_counter()
    try:
        synthesize_edge_tts(
            text=text,
            output_path=current_out,
            voice=current_voice,
            rate=current_rate,
            pitch=current_pitch,
        )
        result["current"].update(
            {
                "ok": True,
                "voice": current_voice,
                "path": str(current_out),
                "bytes": current_out.stat().st_size,
                "elapsed_sec": round(time.perf_counter() - t0, 3),
            }
        )
    except Exception as exc:  # noqa: BLE001
        result["current"]["error"] = str(exc)

    t1 = time.perf_counter()
    try:
        synthesize_openai_compatible(
            text=text,
            output_path=vibe_out,
            base_url=vibe_base_url,
            api_key=vibe_api_key,
            model=vibe_model,
            voice=vibe_voice,
            response_format=vibe_format,
            timeout_sec=vibe_timeout,
        )
        result["vibevoice"].update(
            {
                "ok": True,
                "model": vibe_model,
                "voice": vibe_voice,
                "path": str(vibe_out),
                "bytes": vibe_out.stat().st_size,
                "elapsed_sec": round(time.perf_counter() - t1, 3),
            }
        )
    except Exception as exc:  # noqa: BLE001
        result["vibevoice"]["error"] = str(exc)

    report_path = out_dir / f"tts_compare_report_{stamp}.json"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["report_path"] = str(report_path)
    return result
