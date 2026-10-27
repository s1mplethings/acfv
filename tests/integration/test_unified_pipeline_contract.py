from __future__ import annotations

import json
from pathlib import Path

from acfv.modular.contracts import (
    ART_AUDIO,
    ART_SCREEN_CONTEXT,
    ART_SCREEN_FRAMES,
    ART_SCREEN_WINDOWS,
    ART_SEGMENTS,
)
from acfv.pipeline.contracts import load_contract_artifacts, validate_contract_artifacts
from acfv.pipeline.orchestrator import run_clip_pipeline


class _Config:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or {}

    def get(self, key: str, default=None):
        return self.payload.get(key, default)


def test_real_clip_run_produces_aligned_contract_artifacts(monkeypatch, tmp_path):
    from acfv.modular.plugins import analyze_segments as analyze_plugin
    from acfv.modular.plugins import extract_audio as extract_audio_plugin
    from acfv.modular.plugins import render_clips as render_plugin
    from acfv.modular.plugins import screen_detect as screen_detect_plugin
    from acfv.modular.plugins import screen_understanding as screen_understanding_plugin
    from acfv.modular.plugins import transcribe_audio as transcribe_plugin

    def _fake_extract_audio(ctx):
        work_audio_dir = Path(ctx.store.run_dir) / "work" / "audio"
        work_audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = work_audio_dir / "demo_16000hz.wav"
        audio_path.write_bytes(b"RIFFfakeWAVE")
        if ctx.progress:
            ctx.progress("audio_extract", 0, 2, "start")
            ctx.progress("audio_extract", 2, 2, "done")
        return {
            ART_AUDIO: {
                "schema_version": "1.0.0",
                "audio_path": str(audio_path),
                "path": str(audio_path),
                "sample_rate": 16000,
                "channels": 1,
                "duration_sec": 12.0,
            }
        }

    def _fake_run_transcribe_subprocess(payload, work_dir, progress_callback=None, checkpoint_callback=None):
        if checkpoint_callback:
            checkpoint_callback({"stage": "single_transcribe_start"})
            checkpoint_callback({"stage": "single_transcribe_ok", "segments": 1})
        return {
            "schema_version": "1.0.0",
            "transcript_path": str(payload["transcript_path"]),
            "language": "en",
            "engine": "fake-subprocess",
            "segments": [{"start": 0.0, "end": 8.0, "text": "hello clip pipeline", "confidence": 0.9, "speaker": "host"}],
        }

    def _fake_screen_detect(ctx):
        return {
            ART_SCREEN_FRAMES: {"schema_version": "1.0.0", "frames": []},
            ART_SCREEN_WINDOWS: {"schema_version": "1.0.0", "status": "disabled", "frames": [], "windows": []},
        }

    def _fake_screen_understanding(ctx):
        return {ART_SCREEN_CONTEXT: {"schema_version": "1.0.0", "timeline": [], "status": "disabled"}}

    def _fake_analyze_segments(ctx):
        payload = {
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
                {"start_ms": 0, "end_ms": 8000, "score": 9.5, "rank": 1, "reason_tags": ["highlight"]},
            ],
        }
        out_path = Path(ctx.store.run_dir) / "work" / "segments.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if ctx.progress:
            ctx.progress("analysis", 1, 1, "done")
        return {ART_SEGMENTS: payload}

    def _fake_cut_video(input_path, output_path, start_time, duration):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"fake-mp4")

    monkeypatch.setattr(extract_audio_plugin.spec, "run", _fake_extract_audio)
    monkeypatch.setattr(transcribe_plugin, "run_transcribe_subprocess_guarded", _fake_run_transcribe_subprocess)
    monkeypatch.setattr(screen_detect_plugin.spec, "run", _fake_screen_detect)
    monkeypatch.setattr(screen_understanding_plugin.spec, "run", _fake_screen_understanding)
    monkeypatch.setattr(analyze_plugin.spec, "run", _fake_analyze_segments)
    monkeypatch.setattr(render_plugin, "cut_video_ffmpeg", _fake_cut_video)

    monkeypatch.chdir(tmp_path)
    video_path = Path("demo.mp4")
    video_path.write_bytes(b"fake-video")
    run_dir = Path("run_real_contract")
    result = run_clip_pipeline(
        input_source=str(video_path),
        chat_path=None,
        config_manager=_Config(
            {
                "ENABLE_VIDEO_EMOTION": False,
                "ENABLE_LLM_HIGHLIGHT": False,
                "ENABLE_SCREEN_DETECT": False,
                "ENABLE_SCREEN_UNDERSTANDING": False,
                "ENABLE_SPEAKER_SEPARATION": False,
                "ENABLE_STREAMER_SUBTITLES": False,
                "ENABLE_SUBTITLE_TRANSLATE": False,
                "ENABLE_ENHANCE": False,
                "MAX_CLIP_COUNT": 1,
                "MIN_CLIP_SEGMENT_SECONDS": 6,
            }
        ),
        run_dir=run_dir,
        output_clips_dir=str(run_dir / "clips"),
    )

    errors = validate_contract_artifacts(run_dir)
    assert errors == []

    artifacts = load_contract_artifacts(run_dir)
    assert len(artifacts["stage_plan"]["stages"]) == 10
    assert artifacts["audio_chunk_manifest"]["chunk_count"] == 1
    assert artifacts["transcript_merged"]["chunk_count"] == 1
    assert len(artifacts["selected_segments"]["segments"]) == 1
    assert artifacts["clip_manifest"]["clip_count"] == 1
    assert artifacts["export_results"]["planned_clip_count"] == 1
    assert artifacts["export_results"]["clip_count"] == 1
    assert result["contract_output"]["stage_plan_json"]
    assert result["contract_output"]["audio_chunk_manifest_json"]
    assert result["contract_output"]["transcript_merged_json"]
    assert result["contract_output"]["selected_segments_json"]
    assert result["contract_output"]["clip_manifest_json"]
    assert result["contract_output"]["export_results_json"]
