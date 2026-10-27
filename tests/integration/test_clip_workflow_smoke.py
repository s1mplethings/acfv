from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.support import (
    FakeLLMClient,
    base_clip_config,
    install_fake_analyze,
    install_fake_llm_client,
    install_fake_transcribe_guard,
    run_clip_pipeline_for_test,
)


pytestmark = pytest.mark.usefixtures("require_ffmpeg")


def test_clip_workflow_smoke_local_core_only(monkeypatch, sample_video_path, tmp_path):
    install_fake_transcribe_guard(monkeypatch)
    install_fake_analyze(monkeypatch)
    run_dir = tmp_path / "core_only"
    result = run_clip_pipeline_for_test(
        run_dir=run_dir,
        video_path=sample_video_path,
        config=base_clip_config(),
    )
    clips = result["clips"]
    assert len(clips) == 1
    assert Path(clips[0]).exists()
    assert (run_dir / "work" / "selected_segments.json").exists()
    assert (run_dir / "work" / "clips_manifest.json").exists()


def test_clip_workflow_smoke_local_with_scene_and_ocr(monkeypatch, sample_video_path, tmp_path):
    install_fake_transcribe_guard(monkeypatch)
    install_fake_analyze(monkeypatch)
    monkeypatch.setattr("acfv.steps.screen_detect.impl._detect_scene_windows_with_pyscenedetect", lambda video_path, max_windows: [(0.0, 5.0)])
    monkeypatch.setattr("acfv.steps.screen_detect.impl.run_rapidvideocr", lambda frame_path: "scene text")
    run_dir = tmp_path / "scene_ocr"
    run_clip_pipeline_for_test(
        run_dir=run_dir,
        video_path=sample_video_path,
        config=base_clip_config({"ENABLE_SCREEN_DETECT": True}),
    )
    payload = json.loads((run_dir / "work" / "screen_detect.json").read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["scene_provider"] == "pyscenedetect"
    assert payload["ocr_provider"] == "rapidvideocr"
    assert payload["frames"][0]["ocr_text_hint"] == "scene text"


def test_clip_workflow_smoke_local_with_whisperx(monkeypatch, sample_video_path, tmp_path):
    calls: list[str] = []
    install_fake_transcribe_guard(monkeypatch, engine_calls=calls)
    install_fake_analyze(monkeypatch)
    run_dir = tmp_path / "whisperx"
    run_clip_pipeline_for_test(
        run_dir=run_dir,
        video_path=sample_video_path,
        config=base_clip_config({"providers": {"asr": {"default": "whisperx"}}}),
    )
    assert calls == ["whisperx"]
    assert (run_dir / "work" / "clips_manifest.json").exists()


def test_clip_workflow_smoke_llm_disabled(monkeypatch, sample_video_path, tmp_path, sample_chat_path):
    install_fake_transcribe_guard(monkeypatch)
    install_fake_analyze(monkeypatch)
    run_dir = tmp_path / "llm_disabled"
    run_clip_pipeline_for_test(
        run_dir=run_dir,
        video_path=sample_video_path,
        chat_path=sample_chat_path,
        config=base_clip_config({"ENABLE_LLM_HIGHLIGHT": False}),
    )
    payload = json.loads((run_dir / "work" / "segments_llm.json").read_text(encoding="utf-8"))
    assert payload["policy"]["source"] == "llm_highlight_passthrough"
    assert payload["policy"]["fallback_reason"] == "llm_highlight_disabled"


def test_clip_workflow_smoke_llm_enabled_when_local_endpoint_unavailable(monkeypatch, sample_video_path, tmp_path, sample_chat_path):
    install_fake_transcribe_guard(monkeypatch)
    install_fake_analyze(monkeypatch)
    install_fake_llm_client(monkeypatch, FakeLLMClient(available=True, provider="ollama", base_url="http://127.0.0.1:11434/v1"))
    monkeypatch.setattr("acfv.steps.llm_highlight.impl._is_quickly_reachable", lambda base_url: False)
    run_dir = tmp_path / "llm_unreachable"
    run_clip_pipeline_for_test(
        run_dir=run_dir,
        video_path=sample_video_path,
        chat_path=sample_chat_path,
        config=base_clip_config(
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
    )
    payload = json.loads((run_dir / "work" / "segments_llm.json").read_text(encoding="utf-8"))
    assert payload["policy"]["source"] == "llm_highlight_passthrough"
    assert payload["policy"]["fallback_reason"].startswith("llm_endpoint_unreachable:")
