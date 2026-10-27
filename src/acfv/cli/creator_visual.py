from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import typer


creator_visual_app = typer.Typer(no_args_is_help=True)
ROOT = Path(__file__).resolve().parents[3]


def _run(script: str, extra: list[str]) -> None:
    command = [sys.executable, str(ROOT / "scripts" / script), *extra]
    raise typer.Exit(subprocess.run(command, cwd=ROOT).returncode)


@creator_visual_app.command("dataset-build")
def dataset_build(output: Path = typer.Option(ROOT / "var/creator-visual-identity-v1", "--output")) -> None:
    _run("build_creator_visual_dataset.py", ["--output", str(output)])


@creator_visual_app.command("benchmark")
def benchmark(manifest: Path = typer.Option(ROOT / "var/creator-visual-identity-v1/visual-dataset-manifest.jsonl", "--manifest")) -> None:
    _run("benchmark_creator_visual_identity.py", ["--manifest", str(manifest)])


@creator_visual_app.command("train")
def train(manifest: Path = typer.Option(ROOT / "var/creator-visual-identity-v1/visual-dataset-manifest.jsonl", "--manifest")) -> None:
    """Train/calibrate the lightweight head through the reproducible benchmark."""
    _run("benchmark_creator_visual_identity.py", ["--manifest", str(manifest)])


@creator_visual_app.command("evaluate")
def evaluate(real: bool = typer.Option(False, "--real", help="Run the fixed 500+500 frame real-media validation")) -> None:
    if real:
        _run("validate_creator_visual_identity_real.py", [])
    path = ROOT / "var/creator-visual-identity-v1/benchmark/visual-holdout-results.json"
    if not path.is_file():
        raise typer.BadParameter("visual holdout report is missing; run benchmark first")
    typer.echo(path.read_text(encoding="utf-8"))


@creator_visual_app.command("status")
def status() -> None:
    config_path = ROOT / "config/creator_visual_identity.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    classifier = ROOT / payload["classifier_path"]
    payload["classifier_available"] = classifier.is_file()
    payload["dataset_available"] = (ROOT / "var/creator-visual-identity-v1/visual-dataset-manifest.jsonl").is_file()
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
