from __future__ import annotations

import typer

from acfv.conversation import GroundedConversationService
from acfv.config.config import ConfigManager
from acfv.library import LibraryService, RecordingStatus
from acfv.llm import get_default_client
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex, SearchScope


live_app = typer.Typer(no_args_is_help=True)


@live_app.command("status")
def status() -> None:
    library = LibraryService()
    active = [item for item in library.list_recordings() if item.recording_status == RecordingStatus.RECORDING]
    if not active:
        typer.echo("No active live recordings.")
        return
    for recording in active:
        count = len(library.repository.list_moments(recording_id=recording.id))
        typer.echo(f"{recording.id}\t{recording.title}\t{recording.recording_status.value}\tmoments={count}")


@live_app.command("search")
def search_live(recording_id: str, query: str) -> None:
    library = LibraryService()
    index = PersistentMomentIndex(library.repository)
    retrieval = HybridRetrievalService(library.repository, index)
    answer = GroundedConversationService(retrieval, llm_client=get_default_client(config_manager=ConfigManager())).ask(
        query,
        scope=SearchScope.LIVE_SESSION,
        recording_id=recording_id,
    )
    typer.echo(f"Conversation mode: {answer.runtime_mode.value}")
    typer.echo(answer.answer)
    for card in answer.evidence_cards:
        typer.echo(f"{card.moment_id}\t{card.moment_status}\t{card.start_ms}-{card.end_ms}\t{card.transcript_excerpt}")
