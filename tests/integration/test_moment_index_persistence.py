from pathlib import Path

import numpy as np

from acfv.library import LibraryService
from acfv.moments import MomentService
from acfv.retrieval import PersistentMomentIndex


TERMS = ["overwatch", "minecraft", "drawing", "cooking", "music", "travel", "coding", "cats", "movies", "books"]


def _encoder(texts):
    vectors = []
    for text in texts:
        lowered = text.lower()
        vector = np.asarray([float(lowered.count(term)) for term in TERMS], dtype=np.float32)
        if not vector.any():
            vector[-1] = 0.01
        vectors.append(vector)
    return np.stack(vectors)


def test_index_survives_restart_across_ten_recordings(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    index_root = tmp_path / "moment_index"
    library = LibraryService(db_path)
    creator = library.create_creator("Alice")
    expected = None
    for number, term in enumerate(TERMS):
        recording = library.register_recording(creator_id=creator.id, title=f"Session {number}", require_file=False)
        moment = MomentService(library.repository).ingest_incremental(
            recording.id,
            {"segments": [{"start": 0, "end": 3, "text": f"today we talk about {term}"}]},
        )[0]
        if term == "overwatch":
            expected = moment.id

    index = PersistentMomentIndex(library.repository, index_root, encoder=_encoder)
    assert index.rebuild() == 10
    assert index.search("overwatch", top_k=1)[0].moment_id == expected

    reopened = LibraryService(db_path)
    reopened_index = PersistentMomentIndex(reopened.repository, index_root, encoder=_encoder)
    assert reopened_index.search("overwatch", top_k=1)[0].moment_id == expected
    assert (index_root / "manifest.json").is_file()
    assert (index_root / "embeddings.npy").is_file()


def test_empty_or_scoped_index_returns_only_allowed_evidence(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    index = PersistentMomentIndex(library.repository, tmp_path / "index", encoder=_encoder)
    assert index.search("anything") == []
    creator_a = library.create_creator("Alice")
    creator_b = library.create_creator("Bob")
    for creator in (creator_a, creator_b):
        recording = library.register_recording(creator_id=creator.id, title="Game", require_file=False)
        MomentService(library.repository).ingest_incremental(recording.id, {"segments": [{"start": 0, "end": 2, "text": "overwatch match"}]})
    index.rebuild()

    hits = index.search("overwatch", creator_id=creator_b.id)
    assert hits
    assert library.repository.get_moment(hits[0].moment_id).creator_id == creator_b.id


def test_search_text_deduplicates_identical_summary_and_transcript() -> None:
    from acfv.moments.models import Moment

    moment = Moment(
        stable_key="same", creator_id="creator", recording_id="recording",
        start_ms=0, end_ms=1_000, summary="same evidence", transcript_text="same evidence",
    )
    row = PersistentMomentIndex._row(0, moment)
    assert row.search_text == "same evidence"


def test_search_text_can_include_bounded_neighbor_context() -> None:
    from acfv.moments.models import Moment

    moment = Moment(
        stable_key="center", creator_id="creator", recording_id="recording",
        start_ms=1_000, end_ms=2_000, summary="center", transcript_text="center evidence",
    )
    row = PersistentMomentIndex._row(0, moment, ("previous sentence", "next sentence"))
    assert "center evidence" in row.search_text
    assert "previous sentence" in row.search_text
    assert "next sentence" in row.search_text
