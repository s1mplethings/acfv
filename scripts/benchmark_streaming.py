#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
RUNTIME_ONLY_FIELDS = {
    "attempt",
    "worker_id",
    "started_at",
    "finished_at",
    "error_summary",
    "result_path",
    "output_video",
    "subtitle_path",
    "thumbnail_path",
    "running",
    "progress",
}
EXPECTED_RUNTIME_FILES = {"transcribe_runtime.json", "render_runtime.json", "events.jsonl"}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_command(cmd: list[str], *, cwd: Path = ROOT, timeout: float | None = None) -> dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return {
            "cmd": cmd,
            "returncode": proc.returncode,
            "elapsed_sec": round(time.time() - started, 3),
            "stdout_tail": (proc.stdout or "")[-4000:],
            "stderr_tail": (proc.stderr or "")[-4000:],
        }
    except Exception as exc:
        return {
            "cmd": cmd,
            "returncode": 999,
            "elapsed_sec": round(time.time() - started, 3),
            "error": str(exc),
        }


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _seconds_between(base: datetime | None, value: datetime | None) -> float | None:
    if base is None or value is None:
        return None
    return round(max(0.0, (value - base).total_seconds()), 3)


def _first_line(text: str) -> str | None:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return None


def collect_environment(
    *,
    case_id: str,
    input_video: str | None,
    config_path: str | None,
    output_dir: str | None,
    gui_mode: bool = False,
) -> dict[str, Any]:
    git = _run_command(["git", "rev-parse", "HEAD"])
    ffmpeg = _run_command(["ffmpeg", "-version"], timeout=10)
    ffprobe_duration = None
    if input_video:
        probe = _run_command(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                input_video,
            ],
            timeout=30,
        )
        try:
            ffprobe_duration = round(float((probe.get("stdout_tail") or "").strip()), 3)
        except Exception:
            ffprobe_duration = None
    gpu = _collect_gpu_info()
    config_payload = _read_config(config_path)
    return {
        "schema_version": "1.0.0",
        "created_at": _utcnow(),
        "case_id": case_id,
        "commit": (git.get("stdout_tail") or "").strip() if git.get("returncode") == 0 else "unknown",
        "python": sys.version.replace("\n", " "),
        "python_executable": sys.executable,
        "os": platform.platform(),
        "cuda": gpu.get("cuda"),
        "gpu": gpu.get("gpus"),
        "ffmpeg": _first_line(ffmpeg.get("stdout_tail") or "") if ffmpeg.get("returncode") == 0 else None,
        "gui_mode": bool(gui_mode),
        "input_video": input_video,
        "input_video_duration_sec": ffprobe_duration,
        "config_path": config_path,
        "output_dir": output_dir,
        "gpu_asr_pool.max_workers": _config_get(config_payload, "gpu_asr_pool.max_workers"),
        "render_pool.max_workers": _config_get(config_payload, "render_pool.max_workers"),
    }


def _read_config(config_path: str | None) -> dict[str, Any]:
    if not config_path:
        return {}
    try:
        import yaml

        payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _config_get(payload: dict[str, Any], key: str) -> Any:
    if key in payload:
        return payload[key]
    cur: Any = payload
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _collect_gpu_info() -> dict[str, Any]:
    query = _run_command(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version,cuda_version",
            "--format=csv,noheader,nounits",
        ],
        timeout=10,
    )
    if query.get("returncode") != 0:
        return {"cuda": None, "gpus": [], "available": False}
    gpus = []
    cuda = None
    for line in (query.get("stdout_tail") or "").splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 4:
            cuda = parts[3]
            gpus.append({"name": parts[0], "memory_total_mb": parts[1], "driver": parts[2], "cuda": parts[3]})
    return {"cuda": cuda, "gpus": gpus, "available": bool(gpus)}


def run_preflight(mode: str) -> list[dict[str, Any]]:
    if mode == "none":
        return []
    checks = [
        [sys.executable, "-m", "compileall", "-q", "src"],
        [sys.executable, "-m", "acfv.cli", "--help"],
        [sys.executable, "-m", "acfv.cli", "gui", "--help"],
        [sys.executable, "-m", "acfv.cli", "pipe", "clip", "--help"],
    ]
    if mode == "verify":
        checks = [["powershell", "-ExecutionPolicy", "Bypass", "-File", "scripts\\verify.ps1"]]
    return [_run_command(cmd) for cmd in checks]


class ResourceSampler:
    def __init__(self, interval_sec: float = 2.0) -> None:
        self.interval_sec = max(0.5, float(interval_sec or 2.0))
        self.samples: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if _run_command(["nvidia-smi", "-L"], timeout=5).get("returncode") != 0:
            return
        self._thread = threading.Thread(target=self._loop, name="benchmark-gpu-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval_sec + 1.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            sample = _run_command(
                [
                    "nvidia-smi",
                    "--query-gpu=timestamp,name,utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                timeout=5,
            )
            if sample.get("returncode") == 0:
                for line in (sample.get("stdout_tail") or "").splitlines():
                    parts = [part.strip() for part in line.split(",")]
                    if len(parts) >= 5:
                        self.samples.append(
                            {
                                "sampled_at": _utcnow(),
                                "gpu_timestamp": parts[0],
                                "gpu_name": parts[1],
                                "gpu_util_pct": _to_float(parts[2]),
                                "memory_used_mb": _to_float(parts[3]),
                                "memory_total_mb": _to_float(parts[4]),
                            }
                        )
            self._stop.wait(self.interval_sec)


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def load_events(run_dir: Path) -> list[dict[str, Any]]:
    events_path = run_dir / "work" / "runtime" / "events.jsonl"
    events: list[dict[str, Any]] = []
    if not events_path.exists():
        return events
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:
            payload = {"event": "malformed_event", "raw": line}
        payload["_parsed_ts"] = _parse_time(payload.get("ts"))
        events.append(payload)
    events.sort(key=lambda item: item.get("_parsed_ts") or datetime.max.replace(tzinfo=timezone.utc))
    return events


def analyze_timeline(run_dir: Path, *, e2e_elapsed_sec: float | None = None) -> dict[str, Any]:
    events = load_events(run_dir)
    base = next((event.get("_parsed_ts") for event in events if event.get("_parsed_ts")), None)

    def first_event(predicate) -> dict[str, Any] | None:
        return next((event for event in events if predicate(event)), None)

    def last_event(predicate) -> dict[str, Any] | None:
        found = [event for event in events if predicate(event)]
        return found[-1] if found else None

    first_chunk = first_event(
        lambda e: e.get("event") == "item_state_changed"
        and e.get("stage") == "transcribe_chunks"
        and e.get("status") == "succeeded"
    )
    first_clip_started = first_event(
        lambda e: e.get("event") == "item_state_changed"
        and e.get("stage") == "render_clips_batch"
        and e.get("status") == "running"
    )
    first_clip_done = first_event(
        lambda e: e.get("event") == "item_state_changed"
        and e.get("stage") == "render_clips_batch"
        and e.get("status") == "succeeded"
    )
    all_transcribe = first_event(
        lambda e: e.get("event") == "runtime_finalized"
        and e.get("stage") == "transcribe_chunks"
        and e.get("status") == "succeeded"
    ) or last_event(lambda e: e.get("stage") == "transcribe_chunks" and e.get("status") == "succeeded")
    render_finished = last_event(
        lambda e: e.get("event") == "runtime_finalized"
        and e.get("stage") == "render_clips_batch"
        and e.get("status") in {"succeeded", "failed", "cancelled"}
    ) or last_event(lambda e: e.get("stage") == "render_clips_batch" and e.get("status") == "succeeded")

    ttfc_k = _seconds_between(base, first_chunk.get("_parsed_ts") if first_chunk else None)
    ttfc = _seconds_between(base, first_clip_done.get("_parsed_ts") if first_clip_done else None)
    tat = _seconds_between(base, all_transcribe.get("_parsed_ts") if all_transcribe else None)
    ttr = _seconds_between(base, render_finished.get("_parsed_ts") if render_finished else None)
    e2e = e2e_elapsed_sec if e2e_elapsed_sec is not None else _seconds_between(
        base,
        events[-1].get("_parsed_ts") if events else None,
    )
    reuse_events = [event for event in events if event.get("event") == "render_reuse_existing_output"]
    return {
        "event_count": len(events),
        "TTFCk": ttfc_k,
        "TTFC": ttfc,
        "TAT": tat,
        "TTR": ttr,
        "E2E": round(e2e, 3) if e2e is not None else None,
        "first_clip_started_before_all_transcribe_done": _event_before(first_clip_started, all_transcribe),
        "first_clip_before_all_transcribe_done": _event_before(first_clip_done, all_transcribe),
        "incremental_merge_seen": any(event.get("event") == "incremental_merge_done" for event in events),
        "clip_work_item_queued_seen": any(event.get("event") == "clip_work_item_queued" for event in events),
        "render_reuse_ok": bool(reuse_events),
        "first_events": {
            "first_chunk_succeeded": _event_brief(first_chunk),
            "first_clip_started": _event_brief(first_clip_started),
            "first_clip_succeeded": _event_brief(first_clip_done),
            "all_transcribe_done": _event_brief(all_transcribe),
            "render_finished": _event_brief(render_finished),
        },
        "events": [_strip_internal_event(event) for event in events],
    }


def _event_before(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    if not left or not right:
        return False
    lt = left.get("_parsed_ts")
    rt = right.get("_parsed_ts")
    return bool(lt and rt and lt < rt)


def _event_brief(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if not event:
        return None
    return {k: v for k, v in _strip_internal_event(event).items() if k in {"ts", "event", "stage", "item_id", "status", "clip_id"}}


def _strip_internal_event(event: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in event.items() if not k.startswith("_")}


def validate_structure(run_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        from acfv.pipeline.contracts import validate_contract_artifacts

        errors.extend(validate_contract_artifacts(run_dir))
    except Exception as exc:
        errors.append(f"contract validation failed to run: {exc}")

    work_dir = run_dir / "work"
    audio_manifest = _read_json(work_dir / "audio_chunk_manifest.json")
    clip_manifest = _read_json(work_dir / "clip_manifest.json")
    export_results = _read_json(work_dir / "export_results.json")
    errors.extend(_forbidden_field_errors("audio_chunk_manifest", audio_manifest))
    errors.extend(_forbidden_field_errors("clip_manifest", clip_manifest))
    errors.extend(_forbidden_field_errors("export_results", export_results))

    runtime_dir = work_dir / "runtime"
    runtime_files = sorted(path.name for path in runtime_dir.iterdir()) if runtime_dir.exists() else []
    unexpected = sorted(set(runtime_files) - EXPECTED_RUNTIME_FILES)
    if unexpected:
        errors.append(f"runtime directory contains non-runtime files: {unexpected}")
    for expected in EXPECTED_RUNTIME_FILES:
        if expected not in runtime_files:
            errors.append(f"runtime directory missing {expected}")
    return {
        "contract_clean": not errors,
        "runtime_separate": not unexpected,
        "runtime_files": runtime_files,
        "errors": errors,
    }


def _forbidden_field_errors(name: str, payload: Any) -> list[str]:
    errors: list[str] = []

    def walk(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in RUNTIME_ONLY_FIELDS:
                    errors.append(f"{name}{path}.{key} must not be in contract artifact")
                walk(value, f"{path}.{key}")
        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                walk(item, f"{path}[{idx}]")

    walk(payload, "")
    return errors


def collect_run(
    *,
    case_id: str,
    benchmark_dir: Path,
    run_dir: Path,
    meta: dict[str, Any],
    preflight: list[dict[str, Any]] | None = None,
    pipeline_result: dict[str, Any] | None = None,
    resource_samples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    structure = validate_structure(run_dir)
    timeline = analyze_timeline(run_dir, e2e_elapsed_sec=(pipeline_result or {}).get("elapsed_sec"))
    timeline["resource_samples"] = resource_samples or []
    results = {
        "schema_version": "1.0.0",
        "case_id": case_id,
        "input_video": meta.get("input_video"),
        "config": meta.get("config_path"),
        "commit": meta.get("commit"),
        "run_dir": str(run_dir),
        "TTFCk": timeline.get("TTFCk"),
        "TTFC": timeline.get("TTFC"),
        "TAT": timeline.get("TAT"),
        "TTR": timeline.get("TTR"),
        "E2E": timeline.get("E2E"),
        "contract_clean": structure.get("contract_clean"),
        "runtime_separate": structure.get("runtime_separate"),
        "first_clip_before_all_transcribe_done": timeline.get("first_clip_before_all_transcribe_done"),
        "cancel_ok": "not_run",
        "render_reuse_ok": timeline.get("render_reuse_ok"),
        "notes": _build_notes(structure, timeline, pipeline_result),
        "structure": structure,
        "timeline": {
            "incremental_merge_seen": timeline.get("incremental_merge_seen"),
            "clip_work_item_queued_seen": timeline.get("clip_work_item_queued_seen"),
            "first_clip_started_before_all_transcribe_done": timeline.get("first_clip_started_before_all_transcribe_done"),
            "event_count": timeline.get("event_count"),
        },
        "preflight": preflight or [],
        "pipeline_result": pipeline_result or {},
    }
    _write_json(benchmark_dir / "meta.json", meta)
    _write_json(benchmark_dir / "results.json", results)
    _write_json(benchmark_dir / "timeline.json", timeline)
    (benchmark_dir / "report.md").write_text(render_report(meta, results, timeline), encoding="utf-8")
    return results


def _build_notes(structure: dict[str, Any], timeline: dict[str, Any], pipeline_result: dict[str, Any] | None) -> list[str]:
    notes = []
    if pipeline_result and pipeline_result.get("returncode") not in {None, 0}:
        notes.append(f"pipeline command failed with exit code {pipeline_result.get('returncode')}")
    notes.extend(structure.get("errors") or [])
    if not timeline.get("first_clip_before_all_transcribe_done"):
        notes.append("streaming proof missing: first clip was not observed before all transcribe done")
    if not timeline.get("incremental_merge_seen"):
        notes.append("incremental_merge_done event not observed")
    return notes


def render_report(meta: dict[str, Any], results: dict[str, Any], timeline: dict[str, Any]) -> str:
    lines = [
        f"# ACFV Streaming Benchmark Report",
        "",
        f"- Case: `{meta.get('case_id')}`",
        f"- Commit: `{meta.get('commit')}`",
        f"- Input: `{meta.get('input_video')}`",
        f"- Duration: `{meta.get('input_video_duration_sec')}` sec",
        f"- Config: `{meta.get('config_path')}`",
        f"- Output: `{meta.get('output_dir')}`",
        f"- Python: `{meta.get('python_executable')}`",
        f"- OS: `{meta.get('os')}`",
        f"- CUDA: `{meta.get('cuda')}`",
        "",
        "## Metrics",
        "",
        f"- TTFCk: `{results.get('TTFCk')}` sec",
        f"- TTFC: `{results.get('TTFC')}` sec",
        f"- TAT: `{results.get('TAT')}` sec",
        f"- TTR: `{results.get('TTR')}` sec",
        f"- E2E: `{results.get('E2E')}` sec",
        "",
        "## Streaming Proof",
        "",
        f"- incremental merge seen: `{timeline.get('incremental_merge_seen', _all_repeat_flag(results, 'incremental_merge_seen'))}`",
        f"- clip work item queued seen: `{timeline.get('clip_work_item_queued_seen', _all_repeat_flag(results, 'clip_work_item_queued_seen'))}`",
        f"- first clip before all transcribe done: `{results.get('first_clip_before_all_transcribe_done')}`",
        f"- render reuse observed: `{results.get('render_reuse_ok')}`",
        "",
        "## Contract / Runtime",
        "",
        f"- contract clean: `{results.get('contract_clean')}`",
        f"- runtime separate: `{results.get('runtime_separate')}`",
        f"- runtime files: `{results.get('structure', {}).get('runtime_files')}`",
    ]
    notes = results.get("notes") or []
    if notes:
        lines.extend(["", "## Notes", ""])
        lines.extend(f"- {note}" for note in notes)
    return "\n".join(lines) + "\n"


def _all_repeat_flag(results: dict[str, Any], key: str) -> Any:
    repeats = results.get("repeats") or []
    if not repeats:
        return None
    values = []
    for repeat in repeats:
        timeline = repeat.get("timeline") or {}
        values.append(bool(timeline.get(key)))
    return all(values)


def run_benchmark(args: argparse.Namespace) -> int:
    run_id = args.run_id or f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{args.case_id}"
    benchmark_dir = Path(args.benchmark_root) / run_id
    repeat_count = max(1, int(args.repeat or 1))
    first_pipeline_run_dir = benchmark_dir / "pipeline" / "run_001"
    benchmark_dir.mkdir(parents=True, exist_ok=True)
    meta = collect_environment(
        case_id=args.case_id,
        input_video=args.input_video,
        config_path=args.config,
        output_dir=str(first_pipeline_run_dir),
        gui_mode=False,
    )
    meta["repeat_count"] = repeat_count
    preflight = run_preflight(args.preflight)
    repeat_results: list[dict[str, Any]] = []
    exit_code = 0
    for repeat_index in range(1, repeat_count + 1):
        pipeline_run_dir = benchmark_dir / "pipeline" / f"run_{repeat_index:03d}"
        repeat_dir = benchmark_dir / "repeats" / f"repeat_{repeat_index:03d}"
        sampler = ResourceSampler(interval_sec=args.sample_interval)
        if not args.no_gpu_sample:
            sampler.start()
        cmd = [sys.executable, "-m", "acfv.cli", "pipe", "clip", "--url", args.input_video, "--out-dir", str(pipeline_run_dir)]
        if args.config:
            cmd.extend(["--cfg", args.config])
        started = time.time()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC) if not env.get("PYTHONPATH") else f"{SRC}{os.pathsep}{env['PYTHONPATH']}"
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        sampler.stop()
        pipeline_result = {
            "cmd": cmd,
            "returncode": proc.returncode,
            "elapsed_sec": round(time.time() - started, 3),
            "stdout_tail": (proc.stdout or "")[-4000:],
            "stderr_tail": (proc.stderr or "")[-4000:],
        }
        repeat_meta = dict(meta, output_dir=str(pipeline_run_dir), repeat_index=repeat_index)
        repeat_results.append(
            collect_run(
                case_id=args.case_id,
                benchmark_dir=repeat_dir,
                run_dir=pipeline_run_dir,
                meta=repeat_meta,
                preflight=preflight if repeat_index == 1 else [],
                pipeline_result=pipeline_result,
                resource_samples=sampler.samples,
            )
        )
        if proc.returncode != 0 and exit_code == 0:
            exit_code = int(proc.returncode)
    aggregate = aggregate_repeats(case_id=args.case_id, meta=meta, repeats=repeat_results, preflight=preflight)
    _write_json(benchmark_dir / "meta.json", meta)
    _write_json(benchmark_dir / "results.json", aggregate)
    _write_json(benchmark_dir / "timeline.json", {"repeats": repeat_results})
    (benchmark_dir / "report.md").write_text(render_report(meta, aggregate, {"resource_samples": []}), encoding="utf-8")
    return exit_code


def aggregate_repeats(*, case_id: str, meta: dict[str, Any], repeats: list[dict[str, Any]], preflight: list[dict[str, Any]]) -> dict[str, Any]:
    def median_metric(name: str) -> float | None:
        values = [item.get(name) for item in repeats if isinstance(item.get(name), (int, float))]
        return round(float(statistics.median(values)), 3) if values else None

    notes: list[str] = []
    for item in repeats:
        notes.extend(item.get("notes") or [])
    return {
        "schema_version": "1.0.0",
        "case_id": case_id,
        "input_video": meta.get("input_video"),
        "config": meta.get("config_path"),
        "commit": meta.get("commit"),
        "repeat_count": len(repeats),
        "TTFCk": median_metric("TTFCk"),
        "TTFC": median_metric("TTFC"),
        "TAT": median_metric("TAT"),
        "TTR": median_metric("TTR"),
        "E2E": median_metric("E2E"),
        "contract_clean": all(bool(item.get("contract_clean")) for item in repeats) if repeats else False,
        "runtime_separate": all(bool(item.get("runtime_separate")) for item in repeats) if repeats else False,
        "first_clip_before_all_transcribe_done": all(
            bool(item.get("first_clip_before_all_transcribe_done")) for item in repeats
        )
        if repeats
        else False,
        "cancel_ok": "not_run",
        "render_reuse_ok": all(bool(item.get("render_reuse_ok")) for item in repeats) if repeats else False,
        "notes": sorted(set(notes)),
        "preflight": preflight,
        "repeats": repeats,
    }


def collect_existing(args: argparse.Namespace) -> int:
    benchmark_dir = Path(args.benchmark_root) / (args.run_id or f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{args.case_id}")
    run_dir = Path(args.run_dir)
    meta = collect_environment(
        case_id=args.case_id,
        input_video=args.input_video,
        config_path=args.config,
        output_dir=str(run_dir),
        gui_mode=bool(args.gui_mode),
    )
    collect_run(case_id=args.case_id, benchmark_dir=benchmark_dir, run_dir=run_dir, meta=meta)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ACFV 2.1.0 streaming benchmark and validation harness")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run CLI pipeline and collect benchmark outputs")
    run.add_argument("--case-id", required=True)
    run.add_argument("--input-video", required=True)
    run.add_argument("--config")
    run.add_argument("--benchmark-root", default="var/benchmarks")
    run.add_argument("--run-id")
    run.add_argument("--preflight", choices=["none", "smoke", "verify"], default="smoke")
    run.add_argument("--repeat", type=int, default=1)
    run.add_argument("--sample-interval", type=float, default=2.0)
    run.add_argument("--no-gpu-sample", action="store_true")
    run.set_defaults(func=run_benchmark)

    collect = sub.add_parser("collect", help="Collect benchmark outputs from an existing run_dir")
    collect.add_argument("--case-id", required=True)
    collect.add_argument("--run-dir", required=True)
    collect.add_argument("--input-video")
    collect.add_argument("--config")
    collect.add_argument("--benchmark-root", default="var/benchmarks")
    collect.add_argument("--run-id")
    collect.add_argument("--gui-mode", action="store_true")
    collect.set_defaults(func=collect_existing)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
