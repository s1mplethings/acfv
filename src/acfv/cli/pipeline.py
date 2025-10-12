import typer
from rich import print
from acfv.configs.settings import Settings
from acfv.utils.logging import setup_logging
from acfv.ingest.twitch import fetch_vod
from acfv.features.audio import extract_audio_features
from acfv.scoring.fusion import fuse_scores
from acfv.selection.selector import select_clips
from acfv.export.editor import export_clips

pipeline_app = typer.Typer(no_args_is_help=True)

@pipeline_app.command("clip")
def clip(
    url: str = typer.Option(..., help="URL 或本地媒体路径"),
    out_dir: str = typer.Option("runs/out", help="输出目录"),
    cfg: str = typer.Option(None, help="YAML 配置路径"),
):
    settings = Settings.from_yaml(cfg) if cfg else Settings()
    setup_logging(settings)
    print("[bold]ACFV[/] pipeline start")

    media_path = fetch_vod(url, workdir=settings.workdir)
    feats = extract_audio_features(media_path, settings)
    scores = fuse_scores(feats, settings)
    clips = select_clips(scores, settings)
    export_clips(media_path, clips, out_dir, settings)

    print(f"[green]Done. Exported {len(clips)} clips →[/] {out_dir}")
