from __future__ import annotations

import typer

from acfv.conversation import GroundedConversationService
from acfv.config.config import ConfigManager
from acfv.library import LibraryService
from acfv.llm import get_default_client
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex, SearchScope


def search_command(query: str, creator: str = typer.Option("", "--creator")) -> None:
    library = LibraryService()
    index = PersistentMomentIndex(library.repository)
    retrieval = HybridRetrievalService(library.repository, index)
    try:
        needs_rebuild = not index.manifest_path.is_file()
        if not needs_rebuild:
            index.rows()
    except RuntimeError:
        needs_rebuild = True
    if needs_rebuild:
        retrieval.rebuild()
    conversation = GroundedConversationService(retrieval, llm_client=get_default_client(config_manager=ConfigManager()))
    scope = SearchScope.CREATOR if creator else SearchScope.ENTIRE_LIBRARY
    answer = conversation.ask(query, scope=scope, creator_id=creator or None)
    typer.echo(f"Conversation mode: {answer.runtime_mode.value}")
    typer.echo(answer.answer)
    for card in answer.evidence_cards:
        typer.echo(f"{card.moment_id}\t{card.recording_title}\t{card.start_ms}-{card.end_ms}\t{card.transcript_excerpt}")
