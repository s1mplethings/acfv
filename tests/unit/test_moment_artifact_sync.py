import json
from pathlib import Path

from acfv.library import LibraryService
from acfv.moments.artifacts import sync_incremental_artifacts


def test_incremental_artifact_sync_updates_stable_provisional_window(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Stream", require_file=False)
    work = tmp_path / "run" / "work"
    work.mkdir(parents=True)
    transcript = work / "transcript_merged.json"
    transcript.write_text(json.dumps({"segments": [{"start": 0, "end": 2, "text": "first"}]}), encoding="utf-8")
    assert sync_incremental_artifacts(library.repository, recording.id, tmp_path / "run") == 1
    transcript.write_text(json.dumps({"segments": [{"start": 0, "end": 5, "text": "first extended evidence"}]}), encoding="utf-8")
    assert sync_incremental_artifacts(library.repository, recording.id, tmp_path / "run") == 1

    moments = library.repository.list_moments(recording_id=recording.id)
    assert len(moments) == 1
    assert moments[0].end_ms == 5_000
    assert moments[0].revision == 2
