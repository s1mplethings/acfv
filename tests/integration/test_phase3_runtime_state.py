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
from acfv.steps.transcribe_audio import impl as transcribe_impl


def _runtime_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _runtime_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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
    events_path = run_dir / "work" / "runtime" / "events.jsonl"
    assert events_path.exists()
    assert "item_state_changed" in events_path.read_text(encoding="utf-8")


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


def test_transcribe_runtime_failure_reconciles_completed_chunks_before_marking_stalled_chunk(monkeypatch, tmp_path):
    ctx = _ctx_for_transcribe(tmp_path, duration_sec=6.0, segment_length=2)

    def _failing_run_transcribe_subprocess(payload, work_dir, progress_callback=None, checkpoint_callback=None):
        chunk_result_dir = Path(payload["chunk_result_dir"])
        result_path = chunk_result_dir / "chunk_0000" / "transcript.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "chunk_id": "chunk_0000",
                    "index": 0,
                    "start_sec": 0.0,
                    "end_sec": 2.0,
                    "language": "en",
                    "segments": [{"start": 0.0, "end": 1.0, "text": "cached"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        if checkpoint_callback:
            checkpoint_callback({"stage": "chunk_transcribe_start", "chunk_index": 0})
            checkpoint_callback({"stage": "chunk_transcribe_start", "chunk_index": 1})
        raise RuntimeError("transcribe subprocess stalled during chunk 1 for 180s")

    monkeypatch.setattr(transcribe_plugin, "run_transcribe_subprocess_guarded", _failing_run_transcribe_subprocess)
    with pytest.raises(RuntimeError):
        transcribe_plugin.spec.run(ctx)

    runtime = _runtime_payload(Path(ctx.store.run_dir) / "work" / "runtime" / "transcribe_runtime.json")
    assert runtime["status"] == "failed"
    assert [item["status"] for item in runtime["chunks"]] == ["succeeded", "failed", "queued"]
    assert runtime["chunks"][0]["result_path"].endswith(r"chunk_0000\transcript.json")
    assert runtime["chunks"][1]["error_summary"].startswith("transcribe subprocess stalled during chunk 1")


def test_render_runtime_success_and_clip_manifest_is_plan_input(monkeypatch, tmp_path):
    ctx = _ctx_for_render(tmp_path)

    def _fake_cut_video(input_path, output_path, start_time, duration):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"fake-clip")

    monkeypatch.setattr(render_plugin, "cut_video_ffmpeg", _fake_cut_video)
    render_plugin.spec.run(ctx)

    run_dir = Path(ctx.store.run_dir)
    clip_manifest = _runtime_payload(run_dir / "work" / "clip_manifest.json")
    render_runtime = transcribe_plugin.read_runtime(run_dir / "work" / "runtime" / "render_runtime.json")

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


def test_transcribe_streaming_window_starts_render_before_all_chunks_done(monkeypatch, tmp_path):
    ctx = _ctx_for_transcribe(tmp_path, duration_sec=4.0, segment_length=2)
    run_dir = Path(ctx.store.run_dir)
    video_path = run_dir / "video.mp4"
    video_path.write_bytes(b"fake-video")
    output_dir = run_dir / "clips"
    ctx.params.update(
        {
            "streaming_fast_path": True,
            "video_path": str(video_path),
            "output_dir": str(output_dir),
            "render_pool_max_workers": 1,
            "streaming_window_chunks": 1,
            "min_clip_segment_seconds": 1.0,
        }
    )
    second_chunk_done = threading.Event()
    render_started_before_second_done = threading.Event()

    def _fake_cut_video(input_path, output_path, start_time, duration):
        if not second_chunk_done.is_set():
            render_started_before_second_done.set()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"fake-clip")

    def _write_chunk(payload, chunk_index, start, end, text):
        result_path = Path(payload["chunk_result_dir"]) / f"chunk_{chunk_index:04d}" / "transcript.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "chunk_id": f"chunk_{chunk_index:04d}",
                    "index": chunk_index,
                    "start_sec": start,
                    "end_sec": end,
                    "segments": [{"start": start, "end": end, "text": text}],
                }
            ),
            encoding="utf-8",
        )
        return result_path

    def _fake_run_transcribe_subprocess(payload, work_dir, progress_callback=None, checkpoint_callback=None):
        first_path = _write_chunk(payload, 0, 0.0, 1.0, "first")
        if checkpoint_callback:
            checkpoint_callback({"stage": "chunk_transcribe_start", "chunk_index": 0})
            checkpoint_callback({"stage": "chunk_transcribe_ok", "chunk_index": 0, "segments": 1, "result_path": str(first_path)})
        deadline = time.time() + 2.0
        while time.time() < deadline and not render_started_before_second_done.is_set():
            time.sleep(0.01)
        second_path = _write_chunk(payload, 1, 2.0, 3.0, "second")
        if checkpoint_callback:
            checkpoint_callback({"stage": "chunk_transcribe_start", "chunk_index": 1})
            checkpoint_callback({"stage": "chunk_transcribe_ok", "chunk_index": 1, "segments": 1, "result_path": str(second_path)})
        second_chunk_done.set()
        return {
            "schema_version": "1.0.0",
            "transcript_path": str(payload["transcript_path"]),
            "language": "en",
            "engine": "fake-subprocess",
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "first"},
                {"start": 2.0, "end": 3.0, "text": "second"},
            ],
        }

    monkeypatch.setattr(transcribe_plugin, "run_transcribe_subprocess_guarded", _fake_run_transcribe_subprocess)
    monkeypatch.setattr(transcribe_plugin, "cut_video_ffmpeg", _fake_cut_video)
    transcribe_plugin.spec.run(ctx)

    assert render_started_before_second_done.is_set()
    events_text = (run_dir / "work" / "runtime" / "events.jsonl").read_text(encoding="utf-8")
    assert "incremental_merge_done" in events_text
    assert "clip_work_item_queued" in events_text
    clip_manifest = _runtime_payload(run_dir / "work" / "audio_chunk_manifest.json")
    assert all(chunk["status"] == "planned" for chunk in clip_manifest["chunks"])


def test_transcribe_streaming_duplicate_window_is_deduplicated(monkeypatch, tmp_path):
    ctx = _ctx_for_transcribe(tmp_path, duration_sec=4.0, segment_length=2)
    run_dir = Path(ctx.store.run_dir)
    video_path = run_dir / "video.mp4"
    video_path.write_bytes(b"fake-video")
    output_dir = run_dir / "clips"
    render_calls: list[tuple[float, float]] = []
    ctx.params.update(
        {
            "streaming_fast_path": True,
            "video_path": str(video_path),
            "output_dir": str(output_dir),
            "render_pool_max_workers": 1,
            "streaming_window_chunks": 1,
            "min_clip_segment_seconds": 1.0,
        }
    )

    def _fake_cut_video(input_path, output_path, start_time, duration):
        render_calls.append((start_time, duration))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"fake-clip")

    def _write_chunk(payload, chunk_index, start, end, text):
        result_path = Path(payload["chunk_result_dir"]) / f"chunk_{chunk_index:04d}" / "transcript.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "chunk_id": f"chunk_{chunk_index:04d}",
                    "index": chunk_index,
                    "start_sec": start,
                    "end_sec": end,
                    "segments": [{"start": start, "end": end, "text": text}],
                }
            ),
            encoding="utf-8",
        )
        return result_path

    def _fake_run_transcribe_subprocess(payload, work_dir, progress_callback=None, checkpoint_callback=None):
        first_path = _write_chunk(payload, 0, 0.0, 1.0, "duplicate-a")
        second_path = _write_chunk(payload, 1, 0.0000001, 1.0000001, "duplicate-b")
        if checkpoint_callback:
            checkpoint_callback({"stage": "chunk_transcribe_start", "chunk_index": 0})
            checkpoint_callback({"stage": "chunk_transcribe_ok", "chunk_index": 0, "segments": 1, "result_path": str(first_path)})
            checkpoint_callback({"stage": "chunk_transcribe_start", "chunk_index": 1})
            checkpoint_callback({"stage": "chunk_transcribe_ok", "chunk_index": 1, "segments": 1, "result_path": str(second_path)})
        return {
            "schema_version": "1.0.0",
            "transcript_path": str(payload["transcript_path"]),
            "language": "en",
            "engine": "fake-subprocess",
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "duplicate-a"},
                {"start": 0.0000001, "end": 1.0000001, "text": "duplicate-b"},
            ],
        }

    monkeypatch.setattr(transcribe_plugin, "run_transcribe_subprocess_guarded", _fake_run_transcribe_subprocess)
    monkeypatch.setattr(transcribe_plugin, "cut_video_ffmpeg", _fake_cut_video)
    transcribe_plugin.spec.run(ctx)

    events = _runtime_events(run_dir / "work" / "runtime" / "events.jsonl")
    render_runtime = transcribe_plugin.read_runtime(run_dir / "work" / "runtime" / "render_runtime.json")

    assert len(render_calls) == 1
    assert render_runtime["total_clips"] == 1
    assert render_runtime["completed_clips"] == 1
    assert sum(1 for event in events if event.get("event") == "clip_work_item_queued") == 1
    dedup_events = [event for event in events if event.get("event") == "clip_work_item_deduplicated"]
    assert len(dedup_events) == 1
    assert dedup_events[0]["window_id"] == "0:1000"


def test_streaming_fast_path_enqueue_guard_skips_duplicate(monkeypatch, tmp_path):
    ctx = _ctx_for_transcribe(tmp_path, duration_sec=2.0, segment_length=2)
    run_dir = Path(ctx.store.run_dir)
    work_dir = run_dir / "work"
    video_path = run_dir / "video.mp4"
    output_dir = run_dir / "clips"
    video_path.write_bytes(b"fake-video")
    render_calls: list[tuple[float, float]] = []

    def _fake_cut_video(input_path, output_path, start_time, duration):
        render_calls.append((start_time, duration))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"fake-clip")

    monkeypatch.setattr(transcribe_plugin, "cut_video_ffmpeg", _fake_cut_video)
    streaming = transcribe_plugin._StreamingFastPath(
        ctx=ctx,
        work_dir=work_dir,
        video_path=str(video_path),
        output_dir=str(output_dir),
        render_workers=1,
        window_chunks=1,
        min_duration_sec=1.0,
    )
    streaming.start()
    item = {
        "clip_id": "clip_001",
        "rank": 1,
        "start_sec": 0.0,
        "end_sec": 1.0,
        "start_ms": 0,
        "end_ms": 1000,
        "window_id": "0:1000",
        "output_video": "clip_001.mp4",
        "reason": "test",
    }

    streaming._enqueue_render_item(item)
    streaming._enqueue_render_item(dict(item, clip_id="clip_002", output_video="clip_002.mp4"))
    streaming.close()

    events = _runtime_events(run_dir / "work" / "runtime" / "events.jsonl")
    render_runtime = _runtime_payload(run_dir / "work" / "runtime" / "render_runtime.json")

    assert len(render_calls) == 1
    assert render_runtime["total_clips"] == 1
    skipped = [event for event in events if event.get("event") == "render_enqueue_skipped_duplicate"]
    assert len(skipped) == 1
    assert skipped[0]["window_id"] == "0:1000"


def test_transcribe_split_uses_io_prefetch_with_single_gpu_worker(monkeypatch, tmp_path):
    audio_path = tmp_path / "canonical.wav"
    audio_path.write_bytes(b"RIFFfakeWAVE")
    events: list[str] = []
    lock = threading.Lock()

    def _fake_extract(source, start_time, end_time, output_path):
        idx = int(Path(output_path).stem.split("_")[1])
        with lock:
            events.append(f"extract_start_{idx}")
        time.sleep(0.05)
        Path(output_path).write_bytes(b"chunk")
        with lock:
            events.append(f"extract_done_{idx}")
        return True

    def _fake_transcribe(model, chunk_path, language, prompt, offset):
        idx = int(Path(chunk_path).stem.split("_")[1])
        with lock:
            events.append(f"gpu_start_{idx}")
        time.sleep(0.1)
        with lock:
            events.append(f"gpu_done_{idx}")
        return ([{"start": offset, "end": offset + 1.0, "text": f"chunk {idx}"}], "en")

    monkeypatch.setattr(transcribe_impl, "extract_audio_segment_safe", _fake_extract)
    monkeypatch.setattr(transcribe_impl, "_transcribe_file", _fake_transcribe)
    monkeypatch.setenv("ACFV_TRANSCRIBE_IO_WORKERS", "2")
    monkeypatch.setenv("ACFV_TRANSCRIBE_PREFETCH_CHUNKS", "2")

    segments, language = transcribe_impl._transcribe_with_splitting(
        object(),
        audio_path,
        4.0,
        "en",
        None,
        2,
        chunk_result_dir=tmp_path / "chunks",
    )

    assert language == "en"
    assert len(segments) == 2
    assert events.index("extract_start_1") < events.index("gpu_done_0")
    assert (tmp_path / "chunks" / "chunk_0000" / "transcript.json").exists()


def test_render_reuse_existing_output_event_still_emitted(monkeypatch, tmp_path):
    ctx = _ctx_for_render(tmp_path)
    run_dir = Path(ctx.store.run_dir)
    output_dir = run_dir / "clips"
    output_dir.mkdir(parents=True, exist_ok=True)
    expected_names = [
        render_plugin.CLIP_NAMING_POLICY.format(rank=1, HHhMMmSSs="00h00m10s", start_ms=10000, end_ms=18000),
        render_plugin.CLIP_NAMING_POLICY.format(rank=2, HHhMMmSSs="00h00m00s", start_ms=0, end_ms=8000),
    ]
    for name in expected_names:
        (output_dir / name).write_bytes(b"existing-clip")

    def _unexpected_cut_video(*args, **kwargs):
        raise AssertionError("existing clip should be reused, not re-rendered")

    monkeypatch.setattr(render_plugin, "cut_video_ffmpeg", _unexpected_cut_video)
    render_plugin.spec.run(ctx)

    events = _runtime_events(run_dir / "work" / "runtime" / "events.jsonl")
    assert sum(1 for event in events if event.get("event") == "render_reuse_existing_output") == 2
