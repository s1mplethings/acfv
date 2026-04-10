import typer
from rich import print
from pathlib import Path
from datetime import datetime
import yaml
from acfv.backend import service as backend_service
from acfv.configs.settings import Settings
from acfv.pipeline.stages import get_stage_plan
from acfv.utils.logging import setup_logging

pipeline_app = typer.Typer(no_args_is_help=True)


class _YamlConfigAdapter:
    def __init__(self, payload: dict | None):
        self.payload = payload or {}

    def get(self, key: str, default=None):
        return self.payload.get(key, default)


def _load_cfg_adapter(path: str | None):
    if not path:
        return None
    try:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    return _YamlConfigAdapter(payload if isinstance(payload, dict) else {})

@pipeline_app.command("clip")
def clip(
    url: str = typer.Option(..., help="Twitch VOD URL / VOD ID / local video path"),
    out_dir: str = typer.Option("runs/out", help="Output root directory"),
    cfg: str = typer.Option(None, help="Path to YAML config"),
    dry_run_plan: bool = typer.Option(False, "--dry-run-plan", help="Print the canonical stage plan and exit"),
):
    if isinstance(dry_run_plan, typer.models.OptionInfo):
        dry_run_plan = bool(dry_run_plan.default)
    settings = Settings.from_yaml(cfg) if cfg else Settings()
    cfg_adapter = _load_cfg_adapter(cfg)
    setup_logging(settings)
    print("[bold]ACFV[/] pipeline start")
    if dry_run_plan:
        typer.echo(yaml.safe_dump({"pipeline": "clip", "stages": get_stage_plan()}, sort_keys=False, allow_unicode=True))
        raise typer.Exit(code=0)

    out_root = Path(out_dir)
    if out_root.name.startswith("run_"):
        run_dir = out_root
    else:
        run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S")
        run_dir = out_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    job = backend_service.create_job(
        video_path=str(url),
        chat_path=None,
        config_manager=cfg_adapter,
        run_dir=run_dir,
        output_clips_dir=str(run_dir),
        metadata={
            "source": "cli",
            "entrypoint": "acfv.cli.pipeline.clip",
            "ingest_workdir": settings.workdir,
        },
    )
    result = backend_service.wait_for_job(job["job_id"])
    if result.get("status") != "succeeded":
        typer.echo(f"[pipeline] job failed: {result.get('error_summary') or result.get('status')}", err=True)
        raise typer.Exit(code=1)

    clips = (result.get("result") or {}).get("clips", [])
    print(f"[green]Done. Exported {len(clips)} clips ->[/] {out_dir}")
