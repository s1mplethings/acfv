from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

from acfv.ingest.twitch import fetch_vod
from acfv.modular.pipeline import run_pipeline

from .stages import write_stage_plan


def run_clip_pipeline(
    *,
    input_source: str,
    chat_path: Optional[str],
    config_manager: Any,
    run_dir: Path,
    output_clips_dir: Optional[str] = None,
    progress_callback: Optional[Callable[[str, int, int, str], None]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    metadata = dict(metadata or {})
    write_stage_plan(run_dir, extra={"input_source": input_source})

    if progress_callback:
        progress_callback("ingest_video", 0, 1, "start")
    workdir = metadata.get("ingest_workdir") or str(run_dir / "work" / "ingest")
    resolved_video_path = fetch_vod(input_source, workdir=workdir, config_manager=config_manager)
    if progress_callback:
        progress_callback("ingest_video", 1, 1, "done")

    result = run_pipeline(
        video_path=str(resolved_video_path),
        chat_path=chat_path,
        config_manager=config_manager,
        run_dir=run_dir,
        output_clips_dir=output_clips_dir,
        progress_callback=progress_callback,
    )
    if isinstance(result, dict):
        result.setdefault("resolved_video_path", str(resolved_video_path))
    return result
