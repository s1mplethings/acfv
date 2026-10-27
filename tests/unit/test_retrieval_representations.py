import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from acfv.library import LibraryService
from acfv.moments.models import Moment, MomentStatus
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex
from acfv.retrieval.index import IndexedMoment, SemanticHit


class TruncatingKeywordEncoder:
    def _encode(self, texts, prefix):
        rows = []
        for text in texts:
            visible = " ".join(str(text).casefold().split()[:40])
            rows.append([float("tailfact" in visible), float("decoy" in visible) + 0.01])
        values = np.asarray(rows, dtype=np.float32)
        values /= np.linalg.norm(values, axis=1, keepdims=True)
        return values

    def encode_queries(self, texts):
        return np.asarray([[1.0, 0.0] for _ in texts], dtype=np.float32)

    def encode_passages(self, texts):
        return self._encode(texts, "passage")


def _final_moment(library, recording_id, creator_id, transcript, evidence):
    return library.repository.save(Moment(
        stable_key=f"test:{len(library.repository.list_moments())}",
        creator_id=creator_id,
        recording_id=recording_id,
        start_ms=0,
        end_ms=120_000,
        status=MomentStatus.FINAL,
        summary="ordinary summary",
        transcript_text=transcript,
        evidence_json=json.dumps(evidence),
    ))


def test_long_local_fact_at_tail_is_recovered_by_passage_without_parent_duplicates(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Long stream", require_file=False)
    units = []
    for index in range(18):
        text = " ".join(["filler"] * 15)
        if index == 16:
            text += " tailfact"
        units.append({"type": "transcript", "start_ms": index * 1000, "end_ms": (index + 1) * 1000, "text": text})
    target = _final_moment(library, recording.id, creator.id, " ".join(item["text"] for item in units), units)
    _final_moment(library, recording.id, creator.id, "decoy " * 20, [{"type": "transcript", "start_ms": 0, "end_ms": 1000, "text": "decoy " * 20}])
    index = PersistentMomentIndex(library.repository, tmp_path / "index", encoder=TruncatingKeywordEncoder())
    retrieval = HybridRetrievalService(library.repository, index, reranker=None, load_default_reranker=False)
    retrieval.rebuild()

    results = retrieval.search("tailfact", top_k=10)

    assert results[0].moment_id == target.id
    assert results[0].debug["winning_representation_type"] == "PASSAGE"
    assert len({item.moment_id for item in results}) == len(results)
    target_representations = [row for row in index.representations() if row.parent_moment_id == target.id]
    assert {row.representation_type for row in target_representations} == {"SUMMARY", "FULL_TRANSCRIPT", "PASSAGE", "NEIGHBOR_CONTEXT"}
    assert any("tailfact" in row.text for row in target_representations if row.representation_type == "PASSAGE")


def test_parent_aggregation_uses_best_hit_plus_bounded_second_hit_only(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    index = PersistentMomentIndex(library.repository, tmp_path / "index", encoder=TruncatingKeywordEncoder())
    assert index.SECOND_HIT_BONUS <= 0.05
    assert 0.90 + index.SECOND_HIT_BONUS * 0.80 < 0.93


def test_dense_80_target_can_enter_top_50_through_fts_fusion(tmp_path: Path, monkeypatch) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Candidates", require_file=False)
    rows = [IndexedMoment(f"m{index}", creator.id, recording.id, 0, 1000, "FINAL", datetime.now(timezone.utc).isoformat(), f"candidate {index}", f"candidate {index}") for index in range(80)]
    index = PersistentMomentIndex(library.repository, tmp_path / "index", encoder=TruncatingKeywordEncoder())
    monkeypatch.setattr(index, "rows", lambda: rows)
    dense = [SemanticHit(row.moment_id, 1 - rank / 1000, f"r{rank}", "PASSAGE", row.search_text, 0, 1000, rank) for rank, row in enumerate(rows, 1)]
    monkeypatch.setattr(index, "search", lambda *args, **kwargs: dense)
    seen = []

    def reranker(_query, texts):
        seen.extend(texts)
        return [float("candidate 79" in text) for text in texts]

    service = HybridRetrievalService(library.repository, index, reranker=reranker)
    monkeypatch.setattr(service, "_lexical_search", lambda *_args: [("m79", "fts79", "PASSAGE", "candidate 79")])
    monkeypatch.setattr(service, "_result", lambda row, score, debug: (row.moment_id, score, debug))

    results = service.search("target", top_k=5, candidate_k=50, dense_k=128, fts_k=128)

    assert len(seen) == 50
    assert "candidate 79" in seen
    assert results[0][0] == "m79"
    assert results[0][2]["dense_rank"] == 80
    assert results[0][2]["fts_rank"] == 1


def test_reranker_cannot_erase_strong_hybrid_recall(tmp_path: Path, monkeypatch) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Candidates", require_file=False)
    rows = [
        IndexedMoment(f"m{index}", creator.id, recording.id, 0, 1000, "FINAL", None, f"candidate {index}", f"candidate {index}")
        for index in range(10)
    ]
    index = PersistentMomentIndex(library.repository, tmp_path / "index", encoder=TruncatingKeywordEncoder())
    monkeypatch.setattr(index, "rows", lambda: rows)
    monkeypatch.setattr(index, "search", lambda *args, **kwargs: [
        SemanticHit(row.moment_id, 1 - rank / 100, f"r{rank}", "PASSAGE", row.search_text, 0, 1000, rank)
        for rank, row in enumerate(rows, 1)
    ])
    service = HybridRetrievalService(
        library.repository,
        index,
        reranker=lambda _query, texts: [float(index) for index, _text in enumerate(texts)],
    )
    monkeypatch.setattr(service, "_lexical_search", lambda *_args: [])
    monkeypatch.setattr(service, "_result", lambda row, score, debug: (row.moment_id, score, debug))

    results = service.search("target", top_k=5, candidate_k=10)

    assert "m0" in {item[0] for item in results}
    assert results[0][2]["fusion_rank"] >= 1
    assert results[0][2]["reranker_rank"] >= 1
    assert "blended_rank_score" in results[0][2]


def test_lexical_query_drops_question_stopwords_without_losing_content_terms() -> None:
    terms = HybridRetrievalService._lexical_terms(
        "What control did she identify as the right trigger in Crow Country?"
    )
    assert terms == ["control", "right", "trigger", "crow", "country"]


def test_corrected_speech_and_background_lyrics_are_separate_representations(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Mixed", require_file=False)
    moment = _final_moment(library, recording.id, creator.id, "raw mixed transcript", [])

    rows = PersistentMomentIndex._representations(moment, None, None, quality_spans=[
        {"start_ms": 0, "end_ms": 1000, "display_text": "corrected spoken sentence", "classification": "SPEECH"},
        {"start_ms": 1000, "end_ms": 2000, "display_text": "もう一回こっち向いて", "classification": "LIKELY_BACKGROUND_LYRICS"},
    ])

    by_type = {row["representation_type"]: row for row in rows}
    assert by_type["CORRECTED_SPEECH"]["text"] == "corrected spoken sentence"
    assert by_type["BACKGROUND_LYRICS"]["text"] == "もう一回こっち向いて"


def test_explicit_lyric_intent_boosts_classified_lyric_representation(tmp_path: Path, monkeypatch) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Candidates", require_file=False)
    rows = [
        IndexedMoment("speech", creator.id, recording.id, 0, 1000, "FINAL", None, "ordinary", "ordinary"),
        IndexedMoment("lyrics", creator.id, recording.id, 0, 1000, "FINAL", None, "lyrics", "lyrics"),
    ]
    index = PersistentMomentIndex(library.repository, tmp_path / "index", encoder=TruncatingKeywordEncoder())
    monkeypatch.setattr(index, "rows", lambda: rows)
    def fake_search(*args, **kwargs):
        if kwargs.get("representation_types"):
            return [SemanticHit("lyrics", 0.8, "lyrics:background_lyrics:0", "BACKGROUND_LYRICS", "もう一回こっち向いて", 0, 1000, 1)]
        return [SemanticHit("speech", 0.9, "speech:passage:0", "PASSAGE", "ordinary", 0, 1000, 1)]
    monkeypatch.setattr(index, "search", fake_search)
    service = HybridRetrievalService(library.repository, index, reranker=None, load_default_reranker=False)
    monkeypatch.setattr(service, "_lexical_search", lambda *_args: [])
    monkeypatch.setattr(service, "_result", lambda row, score, debug: (row.moment_id, score, debug))

    results = service.search("Which Japanese lyrics repeat this line?", top_k=2)

    assert results[0][0] == "lyrics"
    assert results[0][2]["representation_adjustment"] == 0.05


def test_index_rebuild_reuses_only_identical_real_representation_inputs(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Reusable", require_file=False)
    _final_moment(library, recording.id, creator.id, "stable reusable evidence", [
        {"type": "transcript", "start_ms": 0, "end_ms": 1000, "text": "stable reusable evidence"}
    ])
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    PersistentMomentIndex(library.repository, first_root, encoder=TruncatingKeywordEncoder()).rebuild()

    second = PersistentMomentIndex(
        library.repository, second_root, encoder=TruncatingKeywordEncoder(), reuse_root=first_root
    )
    second.rebuild()
    manifest = json.loads((second_root / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["embedding_reuse"]["reused"] == len(manifest["representations"])
    assert manifest["embedding_reuse"]["encoded"] == 0


def test_temporal_question_prefers_bounded_neighbor_context(tmp_path: Path, monkeypatch) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Context", require_file=False)
    target = _final_moment(library, recording.id, creator.id, "Where did the music go?", [])
    index = PersistentMomentIndex(library.repository, tmp_path / "index", encoder=TruncatingKeywordEncoder())
    rows = [
        __import__("acfv.retrieval.index", fromlist=["IndexedRepresentation"]).IndexedRepresentation(
            0, f"{target.id}:summary:0", target.id, creator.id, recording.id, 0, 1000, "SUMMARY", "Where did the music go?"
        ),
        __import__("acfv.retrieval.index", fromlist=["IndexedRepresentation"]).IndexedRepresentation(
            1, f"{target.id}:neighbor_context:0", target.id, creator.id, recording.id, 0, 1000, "NEIGHBOR_CONTEXT", "She changed the design before asking where the music went."
        ),
    ]
    monkeypatch.setattr(index, "representations", lambda: rows)
    monkeypatch.setattr("acfv.retrieval.index.search", lambda *args, **kwargs: ([0, 1], [0.90, 0.88]))

    hit = index.search("What changed before the music went away?", top_k=1)[0]

    assert hit.representation_type == "NEIGHBOR_CONTEXT"
    assert "changed the design" in hit.excerpt
