from __future__ import annotations

import json
from pathlib import Path

import pytest

from acfv.pipeline.contracts import validate_contract_artifacts
from acfv.steps.transcribe_audio import impl as transcribe_impl
from tests.support import (
    base_clip_config,
    install_fake_analyze,
    install_fake_transcribe_guard,
    run_clip_pipeline_for_test,
)


pytestmark = pytest.mark.usefixtures("require_ffmpeg")


def test_clip_workflow_e2e_local_sample_real_main_chain(monkeypatch, sample_video_path, contract_run_dir):
    install_fake_transcribe_guard(monkeypatch)
    install_fake_analyze(monkeypatch)
    result = run_clip_pipeline_for_test(
        run_dir=contract_run_dir,
        video_path=sample_video_path,
        config=base_clip_config(),
    )
    assert len(result["clips"]) == 1
    assert Path(result["clips"][0]).exists()
    assert validate_contract_artifacts(contract_run_dir) == []


def test_clip_workflow_e2e_twitch_vod_input_chain(monkeypatch, sample_video_path, tmp_path):
    install_fake_transcribe_guard(monkeypatch)
    install_fake_analyze(monkeypatch)

    def _fake_download(vod_id: str, workdir_path: Path) -> Path:
        return sample_video_path

    monkeypatch.setattr("acfv.providers.download.download_twitch_vod", _fake_download)
    result = run_clip_pipeline_for_test(
        run_dir=tmp_path / "twitch_vod",
        video_path=sample_video_path,
        input_source="https://www.twitch.tv/videos/987654321",
        config=base_clip_config({"providers": {"download": {"default": "twitch-downloader"}}}),
    )
    assert result["resolved_video_path"] == str(sample_video_path)
    assert len(result["clips"]) == 1
    assert Path(result["clips"][0]).exists()


def test_clip_workflow_e2e_asr_fallback_chain(monkeypatch, sample_video_path, tmp_path):
    install_fake_analyze(monkeypatch)
    calls: list[str] = []

    def _fake_run(payload, work_dir, progress_callback=None, checkpoint_callback=None):
        calls.append(str(payload.get("engine")))
        if len(calls) == 1:
            raise RuntimeError("primary asr failed")
        transcript = {
            "schema_version": "1.0.0",
            "transcript_path": str(payload["transcript_path"]),
            "language": "en",
            "engine": str(payload.get("engine")),
            "segments": [{"start": 0.0, "end": 8.0, "text": "fallback transcript"}],
        }
        Path(payload["transcript_path"]).write_text(
            json.dumps(transcript, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return transcript

    monkeypatch.setattr(transcribe_impl, "_run_transcribe_subprocess", _fake_run)
    monkeypatch.setattr(transcribe_impl, "FASTER_WHISPER_AVAILABLE", False)
    monkeypatch.setattr(transcribe_impl, "WHISPERX_AVAILABLE", False)

    result = run_clip_pipeline_for_test(
        run_dir=tmp_path / "fallback_chain",
        video_path=sample_video_path,
        config=base_clip_config({"providers": {"asr": {"default": "faster-whisper"}}}),
    )
    assert calls == ["faster-whisper", "openai-whisper"]
    assert len(result["clips"]) == 1
    assert Path(result["clips"][0]).exists()
