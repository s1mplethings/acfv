from __future__ import annotations

import json
from pathlib import Path

import typer

from acfv.library import VodDownloadService


download_app = typer.Typer(no_args_is_help=True)


@download_app.command("vod")
def download_vod(
    source: str = typer.Argument(..., help="Twitch VOD URL or numeric VOD ID"),
    start_seconds: float | None = typer.Option(None, "--start", min=0, help="Optional range start in seconds"),
    end_seconds: float | None = typer.Option(None, "--end", min=0, help="Optional range end in seconds"),
    media_root: Path | None = typer.Option(None, help="Canonical media root override"),
    process: bool = typer.Option(True, "--process/--no-process", help="Submit validated media to the canonical pipeline"),
) -> None:
    service = VodDownloadService(media_root=media_root)
    job = service.discover(
        source,
        start_ms=int(start_seconds * 1000) if start_seconds is not None else None,
        end_ms=int(end_seconds * 1000) if end_seconds is not None else None,
    )

    def progress(update: dict) -> None:
        typer.echo(json.dumps({"download_id": job.id, "state": "DOWNLOADING", **update}, ensure_ascii=False))

    job = service.download(
        job.id,
        auto_process=process,
        wait_for_processing=process,
        progress_callback=progress,
    )
    typer.echo(json.dumps({
        "download_id": job.id,
        "recording_id": job.recording_id,
        "status": job.status.value,
        "final_path": job.final_path,
    }, ensure_ascii=False))


@download_app.command("status")
def download_status(download_id: str) -> None:
    service = VodDownloadService()
    job = service.refresh_processing_status(download_id)
    typer.echo(json.dumps({
        "download_id": job.id,
        "recording_id": job.recording_id,
        "status": job.status.value,
        "downloaded_bytes": job.downloaded_bytes,
        "total_bytes": job.total_bytes,
        "percent": job.percent,
        "speed_bps": job.speed_bps,
        "eta_seconds": job.eta_seconds,
        "retry_count": job.retry_count,
        "final_path": job.final_path,
        "error": job.error_message,
    }, ensure_ascii=False))
