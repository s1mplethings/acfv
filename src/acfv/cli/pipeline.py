import typer
from rich import print
from pathlib import Path
from acfv.configs.settings import Settings
from acfv.utils.logging import setup_logging
from acfv.ingest.twitch import fetch_vod
from acfv.modular.pipeline import run_pipeline

pipeline_app = typer.Typer(no_args_is_help=True)

@pipeline_app.command("clip")
def clip(
    url: str = typer.Option(..., help="URL ???????"),
    out_dir: str = typer.Option("runs/out", help="????"),
    cfg: str = typer.Option(None, help="YAML ????"),
):
    settings = Settings.from_yaml(cfg) if cfg else Settings()
    setup_logging(settings)
    print("[bold]ACFV[/] pipeline start")

    media_path = fetch_vod(url, workdir=settings.workdir)
    run_dir = Path(out_dir)
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
