from pathlib import Path

from acfv.library import LibraryService, RecordingStatus
from acfv.moments import MomentService, MomentStatus


def test_incremental_transcript_creates_searchable_persistent_moment(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    library = LibraryService(db_path)
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Live session", recording_status=RecordingStatus.RECORDING, require_file=False)
    moments = MomentService(library.repository)

    created = moments.ingest_incremental(
        recording.id,
        {"segments": [{"start": 2.0, "end": 6.0, "text": "I want to play Overwatch tonight", "confidence": 0.9}]},
        {"records": [{"timestamp": 3.0, "message": "OW lets go"}]},
        transcript_artifact="work/transcript_merged.json",
        chat_artifact="work/chat.json",
    )

    assert created[0].status == MomentStatus.PROVISIONAL
    assert moments.search_live("Overwatch", recording_id=recording.id)[0].id == created[0].id
    assert moments.search_live("Minecraft", recording_id=recording.id) == []

    reopened = LibraryService(db_path)
    persisted = MomentService(reopened.repository).list_moments(recording_id=recording.id)
    assert persisted[0].transcript_text == "I want to play Overwatch tonight"
    assert "OW lets go" in persisted[0].chat_text


def test_incremental_snapshot_is_idempotent_and_chat_alone_creates_nothing(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Live", require_file=False)
    service = MomentService(library.repository)
    transcript = {"segments": [{"start": 0, "end": 4, "text": "same evidence"}]}

    first = service.ingest_incremental(recording.id, transcript)
    second = service.ingest_incremental(recording.id, transcript)
    assert first[0].id == second[0].id
    assert second[0].revision == 2
    assert len(service.list_moments(recording_id=recording.id)) == 1
    assert service.ingest_incremental(recording.id, {"segments": []}, {"records": [{"timestamp": 1, "message": "chat only"}]}) == []
