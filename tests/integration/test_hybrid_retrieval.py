from pathlib import Path
import shutil

import numpy as np

from acfv.library import LibraryService
from acfv.moments import MomentService, MomentStatus
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex, SearchScope


TOPICS = [
    ("overwatch", "she denied being scared after the Overwatch monster appeared"),
    ("minecraft", "building a Minecraft castle with viewers"),
    ("drawing", "drawing a blue dragon on one layer"),
    ("cooking", "cooking spicy noodles for dinner"),
    ("music", "playing new music on guitar"),
    ("travel", "planning travel by train to Kyoto"),
    ("coding", "debugging a Python database migration"),
    ("cats", "the cats knocked over the camera"),
    ("movies", "reviewing science fiction movies"),
    ("books", "recommending mystery books"),
]


def _encoder(texts):
    vectors = []
    for text in texts:
        lowered = text.lower()
        vector = np.asarray([float(lowered.count(topic)) for topic, _ in TOPICS], dtype=np.float32)
        if not vector.any():
            vector[-1] = 0.01
        vectors.append(vector)
    return np.stack(vectors)


def _rerank(query, texts):
    terms = set(query.lower().split())
    return [float(len(terms & set(text.lower().split()))) for text in texts]


def test_ten_query_benchmark_reaches_top_five_gate(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    expected = {}
    for topic, text in TOPICS:
        recording = library.register_recording(creator_id=creator.id, title=f"{topic} stream", require_file=False)
        moment = MomentService(library.repository).ingest_incremental(
            recording.id, {"segments": [{"start": 1, "end": 6, "text": text}]}
        )[0]
        expected[topic] = moment.id
    index = PersistentMomentIndex(library.repository, tmp_path / "index", encoder=_encoder)
    retrieval = HybridRetrievalService(library.repository, index, reranker=_rerank)
    retrieval.rebuild()

    correct = 0
    for topic, _ in TOPICS:
        hits = retrieval.search(topic, top_k=5)
        correct += expected[topic] in {hit.moment_id for hit in hits}

    assert correct >= 7


def test_hybrid_scope_and_evidence_card_fields(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Live Game", require_file=False)
    moment = MomentService(library.repository).ingest_incremental(
        recording.id, {"segments": [{"start": 10, "end": 15, "text": "Overwatch surprise"}]}
    )[0]
    index = PersistentMomentIndex(library.repository, tmp_path / "index", encoder=_encoder)
    retrieval = HybridRetrievalService(library.repository, index, reranker=_rerank)
    retrieval.rebuild()

    hit = retrieval.search("Overwatch", scope=SearchScope.LIVE_SESSION, recording_id=recording.id)[0]
    assert hit.recording_title == "Live Game"
    assert (hit.start_ms, hit.end_ms) == (10_000, 15_000)
    assert hit.evidence[0]["type"] == "transcript"

    moment.status = MomentStatus.FINAL
    library.repository.save(moment)
    retrieval.rebuild()
    assert retrieval.search("Overwatch", scope=SearchScope.LIVE_SESSION, recording_id=recording.id) == []


def test_hybrid_retrieval_releases_fts_database_file(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Search", require_file=False)
    MomentService(library.repository).ingest_incremental(
        recording.id, {"segments": [{"start": 1, "end": 6, "text": "search evidence"}]}
    )
    index_root = tmp_path / "index"
    retrieval = HybridRetrievalService(
        library.repository,
        PersistentMomentIndex(library.repository, index_root, encoder=_encoder),
        reranker=_rerank,
    )
    retrieval.rebuild()
    retrieval.search("search", top_k=1)

    shutil.rmtree(index_root)

    assert not index_root.exists()


def test_recording_scope_applies_only_owning_creator_preference(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator_a = library.create_creator("Creator A")
    creator_b = library.create_creator("Creator B")
    recording_a = library.register_recording(creator_id=creator_a.id, title="A", require_file=False)
    recording_b = library.register_recording(creator_id=creator_b.id, title="B", require_file=False)
    for recording in (recording_a, recording_b):
        MomentService(library.repository).ingest_incremental(
            recording.id,
            {"segments": [
                {"start": 1, "end": 4, "text": "highlight pure gameplay"},
                {"start": 5, "end": 8, "text": "highlight complete talking interaction"},
            ]},
        )
    from acfv.feedback import FeedbackService

    FeedbackService(library.repository).add_preference("不要 gameplay", creator_id=creator_a.id)
    FeedbackService(library.repository).add_preference("优先 gameplay", creator_id=creator_b.id)
    index = PersistentMomentIndex(library.repository, tmp_path / "index", encoder=_encoder)
    retrieval = HybridRetrievalService(
        library.repository, index, reranker=lambda _query, texts: [1.0 for _ in texts]
    )
    retrieval.rebuild()

    results_a = retrieval.search(
        "highlight", scope=SearchScope.RECORDING, recording_id=recording_a.id
    )
    results_b = retrieval.search(
        "highlight", scope=SearchScope.RECORDING, recording_id=recording_b.id
    )

    assert "talking" in results_a[0].transcript_excerpt
    assert "gameplay" in results_b[0].transcript_excerpt
    assert all(result.creator_id == creator_a.id for result in results_a)
    assert all(result.creator_id == creator_b.id for result in results_b)


def test_creator_scope_filters_fts_before_scoped_limit(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    target_creator = library.create_creator("Target Creator")
    noisy_creator = library.create_creator("Noisy Creator")
    for number in range(140):
        recording = library.register_recording(
            creator_id=noisy_creator.id, title=f"Noise {number}", require_file=False
        )
        MomentService(library.repository).ingest_incremental(
            recording.id,
            {"segments": [{"start": 1, "end": 6, "text": f"sharedterm unrelated noise {number}"}]},
        )
    target_recording = library.register_recording(
        creator_id=target_creator.id, title="Target", require_file=False
    )
    target = MomentService(library.repository).ingest_incremental(
        target_recording.id,
        {"segments": [{"start": 1, "end": 6, "text": "sharedterm exact creator evidence"}]},
    )[0]
    index = PersistentMomentIndex(library.repository, tmp_path / "index", encoder=_encoder)
    retrieval = HybridRetrievalService(library.repository, index, reranker=_rerank)
    retrieval.rebuild()

    hits = retrieval.search(
        "sharedterm exact creator evidence",
        top_k=5,
        scope=SearchScope.CREATOR,
        creator_id=target_creator.id,
    )

    assert [item.moment_id for item in hits] == [target.id]
    assert all(item.creator_id == target_creator.id for item in hits)
