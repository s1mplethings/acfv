from __future__ import annotations

from pathlib import Path

import typer

from acfv.library.service import LibraryService
from acfv.library.capture import ensure_twitch_monitor_target

library_app = typer.Typer(no_args_is_help=True)


@library_app.command("add-creator")
def add_creator(twitch_name: str) -> None:
    service = LibraryService()
    creator = service.create_creator(twitch_name)
    source = service.add_source(
        creator.id,
        platform="twitch",
        external_id=twitch_name,
        channel_name=twitch_name,
        channel_url=f"https://www.twitch.tv/{twitch_name}",
    )
    ensure_twitch_monitor_target(source)
    typer.echo(f"{creator.id}\t{creator.display_name}\t{source.channel_name}")


@library_app.command("creators")
def creators() -> None:
    for creator in LibraryService().list_creators():
        typer.echo(f"{creator.id}\t{creator.slug}\t{creator.display_name}")


@library_app.command("add-recording")
def add_recording(path: Path, creator_id: str) -> None:
    recording = LibraryService().add_video(path, creator_id=creator_id)
    typer.echo(f"{recording.id}\t{recording.processing_status.value}\t{recording.local_path}")


@library_app.command("recordings")
def recordings(creator_id: str = "") -> None:
    for recording in LibraryService().list_recordings(creator_id or None):
        typer.echo(
            f"{recording.id}\t{recording.recording_status.value}\t"
            f"{recording.processing_status.value}\t{recording.title}\t{recording.local_path or ''}"
        )
