from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

from acfv.modular.contracts import ART_SEGMENTS
from acfv.pipeline.orchestrator import run_clip_pipeline


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"


class ConfigStub:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self._payload = payload or {}

    @property
    def payload(self) -> dict[str, Any]:
        return self._payload

    @payload.setter
    def payload(self, value: dict[str, Any]) -> None:
        self._payload = value or {}

    @property
    def config(self) -> dict[str, Any]:
        return self._payload

    @config.setter
    def config(self, value: dict[str, Any]) -> None:
        self._payload = value or {}

    @property
    def values(self) -> dict[str, Any]:
        return self._payload

    @values.setter
    def values(self, value: dict[str, Any]) -> None:
        self._payload = value or {}

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._payload:
            return self._payload[key]
        cursor: Any = self._payload
        for part in key.split("."):
            if not isinstance(cursor, dict) or part not in cursor:
                return default
            cursor = cursor[part]
        return cursor


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def base_clip_config(override: dict[str, Any] | None = None) -> ConfigStub:
    payload = {
        "ENABLE_VIDEO_EMOTION": False,
        "ENABLE_SCREEN_DETECT": False,
        "ENABLE_SCREEN_UNDERSTANDING": False,
        "ENABLE_SPEAKER_SEPARATION": False,
        "ENABLE_STREAMER_SUBTITLES": False,
        "ENABLE_SUBTITLE_TRANSLATE": False,
        "ENABLE_ENHANCE": False,
        "ENABLE_LLM_HIGHLIGHT": False,
        "ENABLE_LLM_LOCAL_DISTILL": False,
        "REQUIRE_LLM_API": False,
        "MAX_CLIP_COUNT": 1,
        "MIN_CLIP_SEGMENT_SECONDS": 6,
        "MIN_INTEREST_SEGMENT_DURATION": 6,
        "MIN_CLIP_DURATION": 6,
        "MIN_TARGET_CLIP_DURATION": 6,
        "TARGET_CLIP_DURATION": 8,
        "MAX_TARGET_CLIP_DURATION": 12,
        "MAX_CLIP_DURATION": 12,
        "providers": {
            "download": {"default": "twitch-downloader"},
            "asr": {
                "default": "faster-whisper",
                "common": {"segment_length": 120, "language": "en", "device": "cpu"},
                "faster-whisper": {"model": "tiny"},
                "whisperx": {"model": "tiny"},
                "hf-whisper": {"huggingface_model": "openai/whisper-tiny"},
            },
            "scene": {
                "default": "pyscenedetect",
                "common": {"enabled": False, "interval_sec": 5, "max_frames_per_window": 3},
            },
            "ocr": {
                "default": "rapidvideocr",
                "common": {"enabled": True},
            },
            "llm": {
                "default": "disabled",
            },
        },
    }
    return ConfigStub(deep_merge(payload, override or {}))


def ensure_sample_video(path: Path, duration_sec: float = 10.0) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        return path
    cmd = [
        shutil.which("ffmpeg") or "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s=640x360:r=25:d={duration_sec}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=880:sample_rate=48000:duration={duration_sec}",
        "-shortest",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return path


def write_chat_log(path: Path) -> Path:
    payload = {
        "records": [
            {"timestamp": 1.0, "author": "viewer_a", "message": "nice catch"},
            {"timestamp": 2.5, "author": "viewer_b", "message": "clip this"},
            {"timestamp": 4.0, "author": "viewer_a", "message": "this is the moment"},
        ]
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_contract_segments(
    *,
    start_ms: int = 0,
    end_ms: int = 8000,
    score: float = 9.5,
    reason_tags: Iterable[str] | None = None,
) -> dict[str, Any]:
    tags = list(reason_tags or ["highlight"])
    return {
        "schema_version": "1.0.0",
        "units": "ms",
        "sort": "score_desc_start_ms_asc_end_ms_asc",
        "policy": {
            "min_duration_ms": 6000,
            "max_duration_ms": 60000,
            "merge_gap_ms": 800,
            "allow_overlap": False,
            "clamp_to_duration": True,
            "max_segments": 1,
        },
        "segments": [
            {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "score": score,
                "rank": 1,
                "reason_tags": tags,
            }
        ],
    }


def install_fake_analyze(monkeypatch, segments_payload: dict[str, Any] | None = None) -> None:
    from acfv.modular.plugins import analyze_segments as analyze_plugin

    payload = segments_payload or build_contract_segments()

    def _fake_run(ctx):
        out_path = Path(ctx.store.run_dir) / "work" / "segments.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {ART_SEGMENTS: payload}

    monkeypatch.setattr(analyze_plugin.spec, "run", _fake_run)


def _write_fake_chunk_result(chunk_result_dir: str | None, transcript_payload: dict[str, Any]) -> str | None:
    if not chunk_result_dir:
        return None
    result_path = Path(chunk_result_dir) / "chunk_0000" / "transcript.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(transcript_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(result_path)


def install_fake_transcribe_guard(
    monkeypatch,
    *,
    engine_calls: list[str] | None = None,
    transcript_text: str = "hello clip workflow semantic transcript output",
    start_sec: float = 0.0,
    end_sec: float = 8.0,
) -> None:
    from acfv.modular.plugins import transcribe_audio as transcribe_plugin

    def _fake_run(payload, work_dir, progress_callback=None, checkpoint_callback=None):
        if engine_calls is not None:
            engine_calls.append(str(payload.get("engine")))
        transcript = {
            "schema_version": "1.0.0",
            "transcript_path": str(payload["transcript_path"]),
            "language": "en",
            "engine": str(payload.get("engine") or "fake-asr"),
            "segments": [
                {
                    "start": start_sec,
                    "end": end_sec,
                    "text": transcript_text,
                    "confidence": 0.92,
                    "speaker": "host",
                }
            ],
        }
        result_path = _write_fake_chunk_result(payload.get("chunk_result_dir"), transcript)
        Path(payload["transcript_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(payload["transcript_path"]).write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
        if checkpoint_callback:
            checkpoint_callback({"stage": "single_transcribe_start"})
            checkpoint_callback(
                {
                    "stage": "single_transcribe_ok",
                    "segments": len(transcript["segments"]),
                    "result_path": result_path,
                }
            )
        return transcript

    monkeypatch.setattr(transcribe_plugin, "run_transcribe_subprocess_guarded", _fake_run)


class FakeLLMClient:
    def __init__(
        self,
        *,
        available: bool = True,
        provider: str = "ollama",
        base_url: str = "http://127.0.0.1:11434/v1",
        model: str = "qwen2.5:7b-instruct",
        response: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.available = available
        self.config = type(
            "Cfg",
            (),
            {
                "provider": provider,
                "base_url": base_url,
                "model": model,
            },
        )()
        self._response = response or {
            "segments": [
                {
                    "candidate_id": "cand_001",
                    "start": 0.0,
                    "end": 8.0,
                    "score": 9.8,
                    "highlight_type": "semantic_highlight",
                    "summary": "Strong clip moment",
                    "reason_tags": ["clip"],
                    "why_highlight": "Good local highlight",
                    "confidence": 0.87,
                }
            ]
        }
        self._error = error

    def availability_error(self) -> str | None:
        return None if self.available else "fake client unavailable"

    def complete_json(self, **_kwargs: Any) -> dict[str, Any]:
        if self._error is not None:
            raise self._error
        return copy.deepcopy(self._response)


def install_fake_llm_client(monkeypatch, client: FakeLLMClient) -> None:
    from acfv.steps.llm_highlight import impl as llm_impl

    monkeypatch.setattr(llm_impl, "get_default_client", lambda **_kwargs: client)


def run_clip_pipeline_for_test(
    *,
    run_dir: Path,
    video_path: Path,
    config: ConfigStub,
    chat_path: Path | None = None,
    input_source: str | None = None,
    output_clips_dir: Path | None = None,
) -> dict[str, Any]:
    return run_clip_pipeline(
        input_source=input_source or str(video_path),
        chat_path=str(chat_path) if chat_path else None,
        config_manager=config,
        run_dir=Path(run_dir),
        output_clips_dir=str(output_clips_dir or (Path(run_dir) / "clips")),
    )


def run_contract_check(run_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SRC_PATH) if not pythonpath else f"{SRC_PATH}{os.pathsep}{pythonpath}"
    return subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "contract_checks.py"),
            "--run-dir",
            str(run_dir),
            "--require-artifacts",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
