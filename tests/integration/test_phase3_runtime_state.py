from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from acfv.modular.contracts import ART_AUDIO, ART_AUDIO_HOST, ART_SEGMENTS_LLM, ART_TRANSCRIPT, ART_VIDEO
from acfv.modular.plugins import render_clips as render_plugin
from acfv.modular.plugins import transcribe_audio as transcribe_plugin
from acfv.modular.store import ArtifactStore
from acfv.modular.types import ArtifactEnvelope, ModuleContext


def _runtime_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _ctx_for_transcribe(tmp_path: Path, *, duration_sec: float = 4.0, segment_length: int = 2) -> ModuleContext:
    run_dir = tmp_path / "run_transcribe"
    store = ArtifactStore(run_dir)
    audio_path = run_dir / "input.wav"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"RIFFfakeWAVE")
    inputs = {
        ART_AUDIO: ArtifactEnvelope(
            artifact_id="audio",
            type=ART_AUDIO,
            payload={"path": str(audio_path), "audio_path": str(audio_path), "duration_sec": duration_sec},
        )
    }
    return ModuleContext(inputs=inputs, params={"segment_length": segment_length}, store=store, run_id=run_dir.name)


def _ctx_for_render(tmp_path: Path) -> ModuleContext:
    run_dir = tmp_path / "run_render"
    store = ArtifactStore(run_dir)
    video_path = run_dir / "video.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"fake-video")
    inputs = {
        ART_VIDEO: ArtifactEnvelope(artifact_id="video", type=ART_VIDEO, payload={"path": str(video_path)}),
        ART_SEGMENTS_LLM: ArtifactEnvelope(
            artifact_id="segments",
            type=ART_SEGMENTS_LLM,
            payload={
                "schema_version": "1.0.0",
                "units": "ms",
                "segments": [
                    {"start_ms": 0, "end_ms": 8000, "score": 7.5, "rank": 1},
                    {"start_ms": 10000, "end_ms": 18000, "score": 9.0, "rank": 2},
                ],
            },
        ),
        ART_AUDIO_HOST: ArtifactEnvelope(artifact_id="host", type=ART_AUDIO_HOST, payload={"path": None}),
        ART_TRANSCRIPT: ArtifactEnvelope(artifact_id="transcript", type=ART_TRANSCRIPT, payload={"segments": []}),
    }
    return ModuleContext(inputs=inputs, params={"output_dir": str(run_dir / "clips")}, store=store, run_id=run_dir.name)


def test_transcribe_runtime_success_and_plan_runtime_separation(monkeypatch, tmp_path):
    ctx = _ctx_for_transcribe(tmp_path)
    calls = {"count": 0}

    def _fake_run_transcribe_subprocess(payload, work_dir, progress_callback=None, checkpoint_callback=None):
        calls["count"] += 1
        if checkpoint_callback:
            checkpoint_callback({"stage": "prepare_audio_done", "audio_info": {"duration": 4.0}})
            checkpoint_callback({"stage": "model_loaded", "engine": "fake-subprocess"})
            checkpoint_callback({"stage": "chunk_transcribe_start", "chunk_index": 0})
            checkpoint_callback({"stage": "chunk_transcribe_ok", "chunk_index": 0, "segments": 1})
            checkpoint_callback({"stage": "chunk_transcribe_start", "chunk_index": 1})
            checkpoint_callback({"stage": "chunk_transcribe_ok", "chunk_index": 1, "segments": 1})
        return {
            "schema_version": "1.0.0",
            "transcript_path": str(payload["transcript_path"]),
            "language": "en",
            "engine": "fake-subprocess",
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "chunk-1"},
                {"start": 2.0, "end": 3.0, "text": "chunk-2"},
            ],
        }

    monkeypatch.setattr(transcribe_plugin, "run_transcribe_subprocess_guarded", _fake_run_transcribe_subprocess)
    result = transcribe_plugin.spec.run(ctx)

    run_dir = Path(ctx.store.run_dir)
    manifest = _runtime_payload(run_dir / "work" / "audio_chunk_manifest.json")
    runtime = _runtime_payload(run_dir / "work" / "runtime" / "transcribe_runtime.json")
    transcript = result[ART_TRANSCRIPT]

    assert manifest["chunk_count"] == 2
    assert all(chunk["status"] == "planned" for chunk in manifest["chunks"])
    assert all("attempt" not in chunk and "worker_id" not in chunk for chunk in manifest["chunks"])
    assert calls["count"] == 1
    assert runtime["status"] == "succeeded"
    assert runtime["total_chunks"] == 2
    assert runtime["max_workers"] == 1
    assert runtime["completed_chunks"] == 2
    assert [item["status"] for item in runtime["chunks"]] == ["succeeded", "succeeded"]
    assert [seg["start"] for seg in transcript["segments"]] == [0.0, 2.0]
    assert transcript["language"] == "en"


def test_transcribe_runtime_failure_and_cancel(monkeypatch, tmp_path):
    ctx = _ctx_for_transcribe(tmp_path)

    def _failing_run_transcribe_subprocess(payload, work_dir, progress_callback=None, checkpoint_callback=None):
        if checkpoint_callback:
            checkpoint_callback({"stage": "chunk_transcribe_start", "chunk_index": 0})
        raise RuntimeError("cancelled by test")

    monkeypatch.setattr(transcribe_plugin, "run_transcribe_subprocess_guarded", _failing_run_transcribe_subprocess)
    with pytest.raises(RuntimeError):
        transcribe_plugin.spec.run(ctx)

    runtime = _runtime_payload(Path(ctx.store.run_dir) / "work" / "runtime" / "transcribe_runtime.json")
    assert runtime["status"] == "cancelled"
    assert runtime["chunks"][0]["status"] == "cancelled"
    assert runtime["chunks"][1]["status"] == "cancelled"


def test_render_runtime_success_and_clip_manifest_is_plan_input(monkeypatch, tmp_path):
    ctx = _ctx_for_render(tmp_path)

    def _fake_cut_video(input_path, output_path, start_time, duration):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"fake-clip")

    monkeypatch.setattr(render_plugin, "cut_video_ffmpeg", _fake_cut_video)
    render_plugin.spec.run(ctx)

    run_dir = Path(ctx.store.run_dir)
    clip_manifest = _runtime_payload(run_dir / "work" / "clip_manifest.json")
    render_runtime = _runtime_payload(run_dir / "work" / "runtime" / "render_runtime.json")

    assert clip_manifest["clip_count"] == 2
    assert all(clip["status"] == "planned" for clip in clip_manifest["clips"])
    assert all("attempt" not in clip and "worker_id" not in clip for clip in clip_manifest["clips"])
    assert clip_manifest["clips"][0]["start_ms"] == 10000
    assert render_runtime["status"] == "succeeded"
    assert render_runtime["total_clips"] == 2
    assert render_runtime["completed_clips"] == 2
    assert [item["status"] for item in render_runtime["clips"]] == ["succeeded", "succeeded"]


def test_render_runtime_failure(monkeypatch, tmp_path):
    ctx = _ctx_for_render(tmp_path)

    def _failing_cut_video(input_path, output_path, start_time, duration):
        raise RuntimeError("render failed")

    monkeypatch.setattr(render_plugin, "cut_video_ffmpeg", _failing_cut_video)
    with pytest.raises(RuntimeError):
        render_plugin.spec.run(ctx)

    render_runtime = _runtime_payload(Path(ctx.store.run_dir) / "work" / "runtime" / "render_runtime.json")
    assert render_runtime["status"] == "failed"
    assert render_runtime["clips"][0]["status"] == "failed"


def test_render_pool_allows_clip_level_parallelism(monkeypatch, tmp_path):
    ctx = _ctx_for_render(tmp_path)
    ctx.params["render_pool_max_workers"] = 2
    active = 0
    peak = 0
    lock = threading.Lock()

    def _fake_cut_video(input_path, output_path, start_time, duration):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.2)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"fake-clip")
        with lock:
            active -= 1

    monkeypatch.setattr(render_plugin, "cut_video_ffmpeg", _fake_cut_video)
    render_plugin.spec.run(ctx)

    runtime = _runtime_payload(Path(ctx.store.run_dir) / "work" / "runtime" / "render_runtime.json")
    assert runtime["max_workers"] == 2
    assert peak >= 2
    assert runtime["completed_clips"] == 2
