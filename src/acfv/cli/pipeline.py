import typer
from rich import print
from pathlib import Path
from datetime import datetime
from acfv.configs.settings import Settings
from acfv.utils.logging import setup_logging
from acfv.ingest.twitch import fetch_vod
from acfv.modular.pipeline import run_pipeline

pipeline_app = typer.Typer(no_args_is_help=True)

@pipeline_app.command("clip")
def clip(
    url: str = typer.Option(..., help="Twitch VOD URL / VOD ID / local video path"),
    out_dir: str = typer.Option("runs/out", help="Output root directory"),
    cfg: str = typer.Option(None, help="Path to YAML config"),
):
    settings = Settings.from_yaml(cfg) if cfg else Settings()
    setup_logging(settings)
    print("[bold]ACFV[/] pipeline start")

    try:
        media_path = fetch_vod(url, workdir=settings.workdir)
    except Exception as exc:
        typer.echo(f"[pipeline] failed to resolve input video: {exc}", err=True)
        raise typer.Exit(code=2)
    out_root = Path(out_dir)
    if out_root.name.startswith("run_"):
        run_dir = out_root
    else:
        run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S")
        run_dir = out_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    result = run_pipeline(
        video_path=str(media_path),
        chat_path=None,
        config_manager=None,
        run_dir=run_dir,
        output_clips_dir=str(run_dir),
    )

    clips = result.get("clips", [])
    print(f"[green]Done. Exported {len(clips)} clips ->[/] {out_dir}")
