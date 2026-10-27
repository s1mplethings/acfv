from __future__ import annotations

import json
from pathlib import Path

from acfv.library.repository import LibraryRepository

from .service import MomentService


def sync_incremental_artifacts(repository: LibraryRepository, recording_id: str, run_dir: Path | str) -> int:
    root = Path(run_dir)
    transcript_path = root / "work" / "transcript_merged.json"
    if not transcript_path.is_file():
        transcript_path = root / "work" / "transcription.json"
    if not transcript_path.is_file():
        return 0
    chat_path = root / "work" / "chat.json"
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    chat = json.loads(chat_path.read_text(encoding="utf-8")) if chat_path.is_file() else None
    moments = MomentService(repository).ingest_incremental(
        recording_id,
        transcript,
        chat,
        transcript_artifact=str(transcript_path),
        chat_artifact=str(chat_path) if chat_path.is_file() else None,
    )
    return len(moments)
