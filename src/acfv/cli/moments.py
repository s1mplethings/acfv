from __future__ import annotations

from pathlib import Path

import typer

from acfv.library import LibraryService, resolve_artifact_root
from acfv.moments import MomentFinalizer
from acfv.moments.artifacts import sync_incremental_artifacts

moments_app = typer.Typer(no_args_is_help=True)


@moments_app.command("build")
def build(recording_id: str, artifact_root: Path | None = None) -> None:
    library = LibraryService()
    recording = library.get_recording(recording_id)
    if recording is None:
        raise typer.BadParameter(f"Unknown recording: {recording_id}")
    root = artifact_root or resolve_artifact_root(recording)
    if root is None:
        raise typer.BadParameter("Recording has no artifact root")
    typer.echo(f"provisional_moments={sync_incremental_artifacts(library.repository, recording_id, root)}")


@moments_app.command("finalize")
def finalize(recording_id: str, artifact_root: Path | None = None) -> None:
    library = LibraryService()
    moments = MomentFinalizer(library.repository).finalize_artifacts(recording_id, artifact_root)
    typer.echo(f"final_moments={len(moments)}")
