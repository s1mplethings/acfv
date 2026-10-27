from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .job_manager import JobManager

_manager = JobManager()


def render_review_clip(*, video_path: str, output_path: str, start_ms: int, end_ms: int,
                       subtitle_text: str = "", subtitle_style: Optional[Dict[str, Any]] = None,
                       subtitle_path: str | None = None) -> Dict[str, Any]:
    """Render one reviewed boundary through the canonical render implementation."""
    if end_ms <= start_ms:
        raise ValueError("Clip end must be after start")
    source = Path(video_path)
    if not source.is_file():
        raise FileNotFoundError(f"Recording file not found: {source}")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / "work"
    work.mkdir(parents=True, exist_ok=True)
    selected = {
        "schema_version": "1.0.0",
        "units": "ms",
        "sort": "score_desc_start_ms_asc_end_ms_asc",
        "segments": [{"start_ms": start_ms, "end_ms": end_ms, "score": 1.0, "rank": 1}],
    }
    manifest = {
        "schema_version": "1.0.0",
        "stage": "build_clip_manifest",
        "units": "ms",
        "source_media": str(source.resolve()),
        "clip_count": 1,
        "clips": [{"clip_id": "clip_001", "rank": 1, "start_ms": start_ms, "end_ms": end_ms, "output": {"video": output.name}, "status": "planned"}],
    }
    (work / "selected_segments.json").write_text(json.dumps(selected, indent=2), encoding="utf-8")
    (work / "clip_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    from acfv.steps.render_clips.impl import cut_video_ffmpeg

    temporary = output.with_name(f"{output.stem}.tmp{output.suffix}")
    cut_video_ffmpeg(str(source), str(temporary), start_ms / 1000.0, (end_ms - start_ms) / 1000.0)
    if subtitle_path:
        from acfv.processing.subtitle_render import burn_in

        supplied = Path(subtitle_path)
        if not supplied.is_file():
            raise FileNotFoundError(f"Subtitle file not found: {supplied}")
        burn_in(temporary, supplied, output)
        temporary.unlink(missing_ok=True)
    elif subtitle_text.strip():
        import pysubs2
        from acfv.processing.subtitle_render import apply_style_preset, burn_in

        subtitles = pysubs2.SSAFile()
        subtitles.events.append(
            pysubs2.SSAEvent(start=0, end=end_ms - start_ms, text=subtitle_text.strip())
        )
        raw_ass = work / "edited_subtitle.ass"
        styled_ass = work / "edited_subtitle_styled.ass"
        subtitles.save(str(raw_ass))
        style = dict(subtitle_style or {})
        preset = str(style.pop("preset", "clean"))
        presets = Path(__file__).resolve().parents[3] / "assets" / "subtitle_styles" / "presets.json"
        apply_style_preset(raw_ass, preset, styled_ass, presets, overrides=style)
        burn_in(temporary, styled_ass, output)
        temporary.unlink(missing_ok=True)
    else:
        temporary.replace(output)
    manifest["clips"][0]["status"] = "ok"
    (work / "clips_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"output_path": str(output), "selected_segments": str(work / "selected_segments.json"), "clip_manifest": str(work / "clips_manifest.json")}


def create_job(
    *,
    video_path: str,
    chat_path: Optional[str] = None,
    config_manager: Any = None,
    run_dir: Optional[Path | str] = None,
    output_clips_dir: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    progress_callback=None,
) -> Dict[str, Any]:
    return _manager.create_job(
        video_path=video_path,
        chat_path=chat_path,
        config_manager=config_manager,
        run_dir=run_dir,
        output_clips_dir=output_clips_dir,
        metadata=metadata,
        progress_callback=progress_callback,
    )


def get_job_status(job_id: str) -> Dict[str, Any]:
    return _manager.get_job_status(job_id)


def wait_for_job(job_id: str, timeout: Optional[float] = None) -> Dict[str, Any]:
    return _manager.wait_for_job(job_id, timeout=timeout)


def cancel_job(job_id: str) -> Dict[str, Any]:
    return _manager.cancel_job(job_id)


def list_artifacts(job_id: str):
    return _manager.list_artifacts(job_id)


def get_logs(job_id: str):
    return _manager.get_logs(job_id)


def get_runtime_state(job_id: str) -> Dict[str, Any]:
    return _manager.get_runtime_state(job_id)
