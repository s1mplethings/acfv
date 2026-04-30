from __future__ import annotations

import builtins
import json
import sys
import types
from pathlib import Path

import pytest

from acfv.llm.openai_client import OpenAIClientConfig
from acfv.providers import resolve_asr_profile, resolve_ocr_profile, resolve_scene_profile, resolve_video_source, run_rapidvideocr
from acfv.providers.download import download_twitch_vod
from acfv.steps.llm_highlight.impl import run_llm_highlight
from acfv.steps.screen_detect.impl import run_screen_detect
from acfv.steps.transcribe_audio import impl as transcribe_impl
from tests.support import ConfigStub, FakeLLMClient, base_clip_config, install_fake_llm_client


def _assert_transcript_schema(payload: dict) -> None:
    assert payload["schema_version"] == "1.0.0"
    assert isinstance(payload["transcript_path"], str) and payload["transcript_path"]
    assert isinstance(payload["language"], str) and payload["language"]
    assert isinstance(payload["segments"], list)


def _assert_llm_schema(payload: dict) -> None:
    assert payload["schema_version"] == "1.0.0"
    assert payload["units"] == "ms"
    assert isinstance(payload["policy"], dict)
    assert isinstance(payload["segments"], list)


def test_download_provider_contract_supports_local_inputs(sample_video_path, tmp_path):
    resolved = resolve_video_source(str(sample_video_path), str(tmp_path / "dl"), config_manager=base_clip_config())
    assert resolved == str(sample_video_path)
    assert Path(resolved).exists()


def test_download_provider_contract_falls_back_to_streamlink(monkeypatch, sample_video_path, tmp_path):
    calls: list[str] = []

    def _fail_twitch(vod_id: str, workdir_path: Path) -> Path:
        calls.append(f"twitch:{vod_id}")
        raise RuntimeError("twitchdownloader unavailable")

    def _streamlink(url: str, workdir_path: Path, quality: str = "best") -> Path:
        calls.append(f"streamlink:{quality}")
        return sample_video_path

    monkeypatch.setattr("acfv.providers.download.download_twitch_vod", _fail_twitch)
    monkeypatch.setattr("acfv.providers.download.download_with_streamlink", _streamlink)

    cfg = base_clip_config({"providers": {"download": {"default": "twitch-downloader"}}})
    resolved = resolve_video_source("https://www.twitch.tv/videos/123456", str(tmp_path / "vod"), config_manager=cfg)
    assert resolved == str(sample_video_path)
    assert calls == ["twitch:123456", "streamlink:best"]


def test_download_provider_contract_surfaces_missing_dependency(monkeypatch, tmp_path):
    monkeypatch.setattr("acfv.providers.download.ensure_cli_on_path", lambda auto_install=True: None)
    with pytest.raises(RuntimeError, match="TwitchDownloaderCLI is not available"):
        download_twitch_vod("42", tmp_path)


@pytest.mark.parametrize(
    ("cfg_payload", "expected_provider", "expected_model"),
    [
        (
            {"providers": {"asr": {"default": "faster-whisper", "faster-whisper": {"model": "medium"}}}},
            "faster-whisper",
            "medium",
        ),
        (
            {"providers": {"asr": {"default": "whisperx", "whisperx": {"model": "large-v3"}}}},
            "whisperx",
            "large-v3",
        ),
        (
            {"providers": {"asr": {"default": "hf-whisper", "hf-whisper": {"huggingface_model": "openai/whisper-small"}}}},
            "hf-whisper",
            "medium",
        ),
    ],
)
def test_asr_provider_contract_normalizes_profile_schema(cfg_payload, expected_provider, expected_model):
    profile = resolve_asr_profile(base_clip_config(cfg_payload))
    assert profile["provider"] == expected_provider
    assert profile["model"] == expected_model
    assert set(profile) == {"provider", "model", "hf_model", "language", "device", "segment_length"}


def test_asr_provider_contract_covers_fallback_payload(monkeypatch):
    monkeypatch.setattr(transcribe_impl, "FASTER_WHISPER_AVAILABLE", False)
    monkeypatch.setattr(transcribe_impl, "WHISPERX_AVAILABLE", False)
    fallback = transcribe_impl._build_fallback_payload(
        {
            "source_path": __file__,
            "transcript_path": str(Path(__file__).with_suffix(".json")),
            "engine": "faster-whisper",
            "model_size": "medium",
            "device": "cuda",
        }
    )
    assert fallback["engine"] == "openai-whisper"
    assert fallback["device"] == "cpu"
    assert fallback["model_size"] == "small"


def test_asr_provider_contract_guarded_runner_uses_fallback(monkeypatch, tmp_path):
    transcript_path = tmp_path / "transcript.json"
    calls: list[str] = []

    def _fake_run(payload, work_dir, progress_callback=None, checkpoint_callback=None):
        calls.append(str(payload.get("engine")))
        if len(calls) == 1:
            raise RuntimeError("primary failed")
        payload_out = {
            "schema_version": "1.0.0",
            "transcript_path": str(transcript_path),
            "language": "en",
            "engine": str(payload.get("engine")),
            "segments": [{"start": 0.0, "end": 8.0, "text": "fallback transcript"}],
        }
        transcript_path.write_text(json.dumps(payload_out, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload_out

    monkeypatch.setattr(transcribe_impl, "_run_transcribe_subprocess", _fake_run)
    monkeypatch.setattr(transcribe_impl, "FASTER_WHISPER_AVAILABLE", False)
    monkeypatch.setattr(transcribe_impl, "WHISPERX_AVAILABLE", False)

    result = transcribe_impl.run_transcribe_subprocess_guarded(
        {
            "source_path": __file__,
            "transcript_path": str(transcript_path),
            "engine": "faster-whisper",
            "model_size": "medium",
            "device": "cuda",
        },
        tmp_path,
    )
    _assert_transcript_schema(result)
    assert calls == ["faster-whisper", "openai-whisper"]
    assert result["engine"] == "openai-whisper"


def test_scene_provider_contract_normalizes_profile_schema():
    cfg = base_clip_config({"ENABLE_SCREEN_DETECT": True, "SCREEN_ENABLE_OCR": True})
    scene = resolve_scene_profile(cfg)
    ocr = resolve_ocr_profile(cfg)
    assert scene["provider"] == "pyscenedetect"
    assert scene["enabled"] is True
    assert ocr["provider"] == "rapidvideocr"
    assert ocr["enabled"] is True


def test_scene_provider_contract_detects_windows_and_frames(monkeypatch, sample_video_path, tmp_path):
    monkeypatch.setattr("acfv.steps.screen_detect.impl._detect_scene_windows_with_pyscenedetect", lambda video_path, max_windows: [(0.0, 5.0)])
    monkeypatch.setattr("acfv.steps.screen_detect.impl.run_rapidvideocr", lambda frame_path: "terminal output")
    payload = run_screen_detect(
        video_path=str(sample_video_path),
        work_dir=tmp_path,
        enabled=True,
        interval_sec=5.0,
        max_frames_per_window=2,
        enable_ocr=True,
        scene_provider="pyscenedetect",
        ocr_provider="rapidvideocr",
    )
    assert payload["schema_version"] == "1.0.0"
    assert payload["status"] == "ok"
    assert payload["scene_provider"] == "pyscenedetect"
    assert payload["ocr_provider"] == "rapidvideocr"
    assert payload["windows"]
    assert payload["frames"]
    assert payload["frames"][0]["ocr_text_hint"] == "terminal output"


def test_scene_provider_contract_falls_back_to_interval_scan(monkeypatch, sample_video_path, tmp_path):
    monkeypatch.setattr("acfv.steps.screen_detect.impl._detect_scene_windows_with_pyscenedetect", lambda video_path, max_windows: [])
    payload = run_screen_detect(
        video_path=str(sample_video_path),
        work_dir=tmp_path,
        enabled=True,
        interval_sec=5.0,
        max_frames_per_window=2,
        enable_ocr=False,
        scene_provider="pyscenedetect",
        ocr_provider="rapidvideocr",
    )
    assert payload["status"] == "ok"
    assert len(payload["windows"]) >= 1


def test_scene_provider_contract_reports_missing_cv2(monkeypatch, sample_video_path, tmp_path):
    original_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "cv2":
            raise ImportError("cv2 missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)
    payload = run_screen_detect(video_path=str(sample_video_path), work_dir=tmp_path, enabled=True)
    assert payload["status"] == "cv2_unavailable"
    assert payload["windows"] == []
    assert payload["frames"] == []


def test_ocr_provider_contract_reads_text_from_fake_module(tmp_path, monkeypatch):
    fake_module = types.SimpleNamespace(
        RapidVideOCR=lambda: types.SimpleNamespace(
            run=lambda frame_path: [{"text": "Clip workflow"}, {"text": "OCR ok"}]
        )
    )
    monkeypatch.setitem(sys.modules, "rapid_videocr", fake_module)
    monkeypatch.setitem(sys.modules, "RapidVideOCR", fake_module)
    frame_path = tmp_path / "frame.jpg"
    frame_path.write_bytes(b"fake")
    assert run_rapidvideocr(frame_path) == "Clip workflow OCR ok"


def test_ocr_provider_contract_handles_missing_dependency(monkeypatch, tmp_path):
    original_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name in {"rapid_videocr", "RapidVideOCR"}:
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)
    frame_path = tmp_path / "frame.jpg"
    frame_path.write_bytes(b"fake")
    assert run_rapidvideocr(frame_path) == ""


@pytest.mark.parametrize(
    ("payload", "provider", "base_url"),
    [
        (
            {"providers": {"llm": {"default": "ollama", "ollama": {"base_url": "http://127.0.0.1:11434/v1", "model": "qwen"}}}},
            "ollama",
            "http://127.0.0.1:11434/v1",
        ),
        (
            {"providers": {"llm": {"default": "vllm", "vllm": {"base_url": "http://127.0.0.1:8000/v1", "model": "qwen"}}}},
            "vllm",
            "http://127.0.0.1:8000/v1",
        ),
        (
            {"providers": {"llm": {"default": "disabled"}}},
            "disabled",
            "",
        ),
    ],
)
def test_llm_provider_contract_normalizes_config(payload, provider, base_url):
    cfg = ConfigStub(payload)
    resolved = OpenAIClientConfig.from_sources(config_manager=cfg)
    assert resolved.provider == provider
    assert resolved.base_url == base_url


def test_llm_provider_contract_passthrough_when_disabled(tmp_path):
    payload = run_llm_highlight(
        semantic_segments_payload={"segments": [{"start_ms": 0, "end_ms": 8000, "score": 9.0}]},
        candidate_segments_payload={},
        transcript_payload={"segments": [{"start": 0.0, "end": 8.0, "text": "test"}]},
        chat_payload={"records": []},
        screen_payload={"timeline": []},
        video_emotion_payload=[],
        work_dir=tmp_path,
        config_manager=base_clip_config({"ENABLE_LLM_HIGHLIGHT": False}),
        enabled=False,
    )
    _assert_llm_schema(payload)
    assert payload["policy"]["source"] == "llm_highlight_passthrough"
    assert payload["policy"]["fallback_reason"] == "llm_highlight_disabled"


def test_llm_provider_contract_falls_back_when_local_endpoint_unavailable(monkeypatch, tmp_path):
    install_fake_llm_client(
        monkeypatch,
        FakeLLMClient(available=True, provider="ollama", base_url="http://127.0.0.1:11434/v1"),
    )
    monkeypatch.setattr("acfv.steps.llm_highlight.impl._is_quickly_reachable", lambda base_url: False)
    payload = run_llm_highlight(
        semantic_segments_payload={"segments": [{"start_ms": 0, "end_ms": 8000, "score": 9.0}]},
        candidate_segments_payload={},
        transcript_payload={"segments": [{"start": 0.0, "end": 8.0, "text": "test"}]},
        chat_payload={"records": []},
        screen_payload={"timeline": []},
        video_emotion_payload=[],
        work_dir=tmp_path,
        config_manager=base_clip_config(
            {
                "ENABLE_LLM_HIGHLIGHT": True,
                "providers": {
                    "llm": {
                        "default": "ollama",
                        "ollama": {"base_url": "http://127.0.0.1:11434/v1", "model": "qwen"},
                    }
                },
            }
        ),
        enabled=True,
    )
    _assert_llm_schema(payload)
    assert payload["policy"]["source"] == "llm_highlight_passthrough"
    assert payload["policy"]["fallback_reason"].startswith("llm_endpoint_unreachable:")
