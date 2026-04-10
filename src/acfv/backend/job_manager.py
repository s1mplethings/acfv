from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from acfv.modular.store import ArtifactStore
from acfv.pipeline.orchestrator import run_clip_pipeline
from acfv.pipeline.stages import get_stage_plan, normalize_stage_name
from acfv.runtime.storage import processing_path, runs_out_path

from .job_state import (
    STATUS_CANCELLING,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    JobState,
)

PipelineRunner = Callable[..., Dict[str, Any]]
ProgressCallback = Optional[Callable[[str, int, int, str], None]]


class JobCancelledError(RuntimeError):
    pass


@dataclass
class _JobRuntime:
    state: JobState
    done_event: threading.Event
    cancel_event: threading.Event
    thread: Optional[threading.Thread] = None


class JobManager:
    def __init__(self, pipeline_runner: Optional[PipelineRunner] = None) -> None:
        self._pipeline_runner = pipeline_runner
        self._jobs: Dict[str, _JobRuntime] = {}
        self._lock = threading.RLock()

    def create_job(
        self,
        *,
        video_path: str,
        chat_path: Optional[str],
        config_manager: Any,
        run_dir: Optional[Path | str] = None,
        output_clips_dir: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        progress_callback: ProgressCallback = None,
    ) -> Dict[str, Any]:
        run_dir_path = Path(run_dir) if run_dir is not None else self._create_default_run_dir()
        run_dir_path.mkdir(parents=True, exist_ok=True)
        output_dir = str(output_clips_dir or run_dir_path)

        with self._lock:
            job_id = self._allocate_job_id(run_dir_path.name)
            job_metadata = dict(metadata or {})
            job_metadata.setdefault("stage_plan", get_stage_plan())
            state = JobState(
                job_id=job_id,
                metadata=job_metadata,
                run_dir=str(run_dir_path),
                output_dir=output_dir,
            )
            state.append_log(f"[job] created run_dir={run_dir_path}")
            runtime = _JobRuntime(
                state=state,
                done_event=threading.Event(),
                cancel_event=threading.Event(),
            )
            thread = threading.Thread(
                target=self._run_job,
                name=f"job-{job_id}",
                daemon=True,
                args=(runtime, video_path, chat_path, config_manager, run_dir_path, output_dir, progress_callback),
            )
            runtime.thread = thread
            self._jobs[job_id] = runtime
            thread.start()
            return state.snapshot()

    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        runtime = self._require_job(job_id)
        with self._lock:
            return runtime.state.snapshot()

    def wait_for_job(self, job_id: str, timeout: Optional[float] = None) -> Dict[str, Any]:
        runtime = self._require_job(job_id)
        runtime.done_event.wait(timeout=timeout)
        return self.get_job_status(job_id)

    def cancel_job(self, job_id: str) -> Dict[str, Any]:
        runtime = self._require_job(job_id)
        with self._lock:
            runtime.cancel_event.set()
            if runtime.state.status == STATUS_PENDING:
                runtime.state.status = STATUS_CANCELLED
            elif runtime.state.status == STATUS_RUNNING:
                runtime.state.status = STATUS_CANCELLING
            runtime.state.append_log("[job] cancel requested")
            runtime.state.touch()
        self._write_stop_flag()
        return self.get_job_status(job_id)

    def list_artifacts(self, job_id: str) -> list[Dict[str, Any]]:
        runtime = self._require_job(job_id)
        with self._lock:
            return list(runtime.state.artifacts)

    def get_logs(self, job_id: str) -> list[str]:
        runtime = self._require_job(job_id)
        with self._lock:
            return list(runtime.state.logs)

    def get_runtime_state(self, job_id: str) -> Dict[str, Any]:
        runtime = self._require_job(job_id)
        with self._lock:
            run_dir = runtime.state.run_dir
        if not run_dir:
            return {}
        runtime_dir = Path(run_dir) / "work" / "runtime"
        return {
            "transcribe_runtime": self._read_json(runtime_dir / "transcribe_runtime.json"),
            "render_runtime": self._read_json(runtime_dir / "render_runtime.json"),
        }

    def _run_job(
        self,
        runtime: _JobRuntime,
        video_path: str,
        chat_path: Optional[str],
        config_manager: Any,
        run_dir: Path,
        output_dir: str,
        progress_callback: ProgressCallback,
    ) -> None:
        state = runtime.state
        try:
            self._clear_stop_flag()
            with self._lock:
                state.status = STATUS_RUNNING
                state.current_stage = "run"
                state.append_log(f"[job] started video={video_path}")

            def _progress(stage: str, current: int, total: int, message: str = "") -> None:
                if runtime.cancel_event.is_set():
                    raise JobCancelledError(f"job {state.job_id} cancelled")
                canonical_stage = normalize_stage_name(stage)
                with self._lock:
                    if canonical_stage:
                        state.current_stage = canonical_stage
                    state.progress.update(current=current, total=total, message=message or "")
                    logged_stage = canonical_stage or str(stage)
                    state.append_log(f"[progress] {logged_stage} {current}/{total} {message or ''}".rstrip())
                if progress_callback:
                    progress_callback(canonical_stage or stage, current, total, message or "")

            if self._pipeline_runner is not None:
                result = self._pipeline_runner(
                    input_source=video_path,
                    chat_path=chat_path,
                    config_manager=config_manager,
                    run_dir=run_dir,
                    output_clips_dir=output_dir,
                    progress_callback=_progress,
                    metadata=state.metadata,
                )
            else:
                result = run_clip_pipeline(
                    input_source=video_path,
                    chat_path=chat_path,
                    config_manager=config_manager,
                    run_dir=run_dir,
                    output_clips_dir=output_dir,
                    progress_callback=_progress,
                    metadata=state.metadata,
                )
            artifacts = self._collect_artifacts(run_dir=run_dir, result=result)
            with self._lock:
                state.result = dict(result or {})
                state.artifacts = artifacts
                if runtime.cancel_event.is_set() or state.status == STATUS_CANCELLING:
                    state.status = STATUS_CANCELLED
                    state.error_summary = "Job cancelled"
                    state.append_log("[job] cancelled")
                else:
                    state.status = STATUS_SUCCEEDED
                    state.current_stage = "completed"
                    state.append_log("[job] completed")
                state.touch()
        except JobCancelledError:
            with self._lock:
                state.status = STATUS_CANCELLED
                state.error_summary = "Job cancelled"
                state.append_log("[job] cancelled")
                state.touch()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                state.status = STATUS_FAILED
                state.error_summary = str(exc)
                state.append_log(f"[job] failed: {exc}")
                state.touch()
        finally:
            runtime.done_event.set()

    def _collect_artifacts(self, *, run_dir: Path, result: Dict[str, Any]) -> list[Dict[str, Any]]:
        refs: list[Dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        def _push(kind: str, name: str, value: str) -> None:
            if not value:
                return
            key = (kind, value)
            if key in seen:
                return
            seen.add(key)
            refs.append({"kind": kind, "name": name, "value": value})

        try:
            store = ArtifactStore(run_dir)
            for artifact_id in store.list_artifacts():
                _push("artifact_id", "artifact_id", artifact_id)
        except Exception:
            pass

        contract_output = {}
        if isinstance(result, dict):
            contract_output = result.get("contract_output") or {}
        if isinstance(contract_output, dict):
            for key, value in contract_output.items():
                if isinstance(value, str):
                    _push("file", key, value)
                elif isinstance(value, list):
                    for idx, item in enumerate(value):
                        if isinstance(item, str):
                            _push("file", f"{key}[{idx}]", item)
        return refs

    def _require_job(self, job_id: str) -> _JobRuntime:
        with self._lock:
            runtime = self._jobs.get(job_id)
        if runtime is None:
            raise KeyError(f"Unknown job_id: {job_id}")
        return runtime

    def _create_default_run_dir(self) -> Path:
        run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S")
        run_dir = runs_out_path(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def _allocate_job_id(self, preferred: str) -> str:
        job_id = preferred
        suffix = 1
        while job_id in self._jobs:
            suffix += 1
            job_id = f"{preferred}_{suffix:02d}"
        return job_id

    def _write_stop_flag(self) -> None:
        try:
            stop_flag = processing_path("stop_flag.txt")
            stop_flag.parent.mkdir(parents=True, exist_ok=True)
            stop_flag.write_text("STOP", encoding="utf-8")
        except Exception:
            pass

    def _clear_stop_flag(self) -> None:
        try:
            stop_flag = processing_path("stop_flag.txt")
            if stop_flag.exists():
                stop_flag.unlink()
        except Exception:
            pass

    def _read_json(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
