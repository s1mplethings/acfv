from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from acfv.pipeline.stages import get_stage_plan


def _load_benchmark_module():
    path = Path("scripts/benchmark_streaming.py").resolve()
    spec = importlib.util.spec_from_file_location("benchmark_streaming", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_fake_contract_run(run_dir: Path) -> None:
    work = run_dir / "work"
    _write_json(work / "stage_plan.json", {"schema_version": "1.0.0", "pipeline": "clip", "stages": get_stage_plan()})
    _write_json(
        work / "audio_chunk_manifest.json",
        {
            "schema_version": "1.0.0",
            "stage": "build_audio_chunk_manifest",
            "audio_path": "audio.wav",
            "segment_length_sec": 60,
            "chunk_count": 2,
            "chunks": [
                {"chunk_id": "chunk_0000", "index": 0, "start_sec": 0.0, "end_sec": 60.0, "status": "planned"},
                {"chunk_id": "chunk_0001", "index": 1, "start_sec": 60.0, "end_sec": 120.0, "status": "planned"},
            ],
        },
    )
    _write_json(
        work / "transcript_merged.json",
        {
            "schema_version": "1.0.0",
            "stage": "merge_transcript",
            "audio_chunk_manifest_path": str(work / "audio_chunk_manifest.json"),
            "chunk_count": 2,
            "segments": [{"start": 0.0, "end": 8.0, "text": "hello"}],
        },
    )
    selected = {
        "schema_version": "1.0.0",
        "units": "ms",
        "sort": "score_desc_start_ms_asc_end_ms_asc",
        "policy": {"max_segments": 1},
        "segments": [{"start_ms": 0, "end_ms": 8000, "score": 9.0, "rank": 1}],
    }
    _write_json(work / "selected_segments.json", selected)
    _write_json(
        work / "clip_manifest.json",
        {
            "schema_version": "1.0.0",
            "stage": "build_clip_manifest",
            "units": "ms",
            "run_id": run_dir.name,
            "source_media": "video.mp4",
            "selected_segments_path": str(work / "selected_segments.json"),
            "naming_policy": "clip_{rank:03d}.mp4",
            "clip_count": 1,
            "clips": [
                {
                    "clip_id": "clip_001",
                    "rank": 1,
                    "start_ms": 0,
                    "end_ms": 8000,
                    "duration_ms": 8000,
                    "status": "planned",
                    "output": {"video": "clip_001.mp4"},
                }
            ],
        },
    )
    _write_json(work / "clips_manifest.json", {"schema_version": "1.0.0", "clips": []})
    _write_json(
        work / "export_results.json",
        {
            "schema_version": "1.0.0",
            "stage": "export_results",
            "run_id": run_dir.name,
            "clip_count": 1,
            "planned_clip_count": 1,
            "selected_segment_count": 1,
            "clips_manifest_path": str(work / "clips_manifest.json"),
            "artifact_refs": {
                "stage_plan": str(work / "stage_plan.json"),
                "audio_chunk_manifest": str(work / "audio_chunk_manifest.json"),
                "transcript_merged": str(work / "transcript_merged.json"),
                "selected_segments": str(work / "selected_segments.json"),
                "clip_manifest": str(work / "clip_manifest.json"),
            },
        },
    )
    runtime = work / "runtime"
    _write_json(runtime / "transcribe_runtime.json", {"status": "succeeded", "total_chunks": 2})
    _write_json(runtime / "render_runtime.json", {"status": "succeeded", "total_clips": 1})
    events = [
        {"ts": "2026-04-10T00:00:00+00:00", "event": "runtime_initialized", "stage": "transcribe_chunks"},
        {"ts": "2026-04-10T00:00:02+00:00", "event": "item_state_changed", "stage": "transcribe_chunks", "item_id": "chunk_0000", "status": "succeeded"},
        {"ts": "2026-04-10T00:00:03+00:00", "event": "incremental_merge_done", "stage": "merge_transcript", "chunk_id": "chunk_0000"},
        {"ts": "2026-04-10T00:00:04+00:00", "event": "clip_work_item_queued", "stage": "build_clip_manifest", "clip_id": "clip_001"},
        {"ts": "2026-04-10T00:00:05+00:00", "event": "item_state_changed", "stage": "render_clips_batch", "item_id": "clip_001", "status": "running"},
        {"ts": "2026-04-10T00:00:06+00:00", "event": "item_state_changed", "stage": "render_clips_batch", "item_id": "clip_001", "status": "succeeded"},
        {"ts": "2026-04-10T00:00:10+00:00", "event": "runtime_finalized", "stage": "transcribe_chunks", "status": "succeeded"},
        {"ts": "2026-04-10T00:00:11+00:00", "event": "render_reuse_existing_output", "stage": "render_clips_batch", "clip_id": "clip_001"},
        {"ts": "2026-04-10T00:00:12+00:00", "event": "runtime_finalized", "stage": "render_clips_batch", "status": "succeeded"},
    ]
    (runtime / "events.jsonl").write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")


def test_benchmark_collects_streaming_metrics_and_writes_reports(tmp_path):
    bench = _load_benchmark_module()
    run_dir = tmp_path / "run_001"
    _write_fake_contract_run(run_dir)

    structure = bench.validate_structure(run_dir)
    timeline = bench.analyze_timeline(run_dir)
    results = bench.collect_run(
        case_id="fake_short",
        benchmark_dir=tmp_path / "bench",
        run_dir=run_dir,
        meta={"case_id": "fake_short", "commit": "abc", "input_video": "demo.mp4", "config_path": None},
    )

    assert structure["contract_clean"] is True
    assert structure["runtime_separate"] is True
    assert timeline["TTFCk"] == 2.0
    assert timeline["TTFC"] == 6.0
    assert timeline["TAT"] == 10.0
    assert timeline["first_clip_before_all_transcribe_done"] is True
    assert results["render_reuse_ok"] is True
    assert (tmp_path / "bench" / "meta.json").exists()
    assert (tmp_path / "bench" / "results.json").exists()
    assert (tmp_path / "bench" / "timeline.json").exists()
    assert (tmp_path / "bench" / "report.md").exists()


def test_benchmark_structure_flags_contract_runtime_pollution(tmp_path):
    bench = _load_benchmark_module()
    run_dir = tmp_path / "run_bad"
    _write_fake_contract_run(run_dir)
    manifest_path = run_dir / "work" / "audio_chunk_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["chunks"][0]["worker_id"] = "gpu_asr_pool:0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "work" / "runtime" / "debug.tmp").write_text("bad", encoding="utf-8")

    structure = bench.validate_structure(run_dir)

    assert structure["contract_clean"] is False
    assert structure["runtime_separate"] is False
    assert any("worker_id" in error for error in structure["errors"])
    assert any("non-runtime files" in error for error in structure["errors"])
