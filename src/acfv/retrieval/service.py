from __future__ import annotations

import json
import logging
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable, Iterable

from acfv.library.repository import LibraryRepository
from acfv.moments.models import MomentStatus
from acfv.ragstack.embeddings.encoder import EmbeddingModelUnavailable

from .index import IndexedMoment, PersistentMomentIndex
from .query import SearchResult, SearchScope
from .reranker import local_cross_encoder


_QUERY_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "did", "do", "does",
    "for", "from", "has", "have", "he", "her", "his", "how", "i", "identify",
    "in", "is", "it", "of", "on", "she", "that", "the", "their", "they",
    "this", "to", "was", "were", "what", "when", "where", "which", "who",
    "why", "with", "you", "your",
}


class HybridRetrievalService:
    FUSION_RANK_WEIGHT = 0.70
    RERANK_WEIGHT = 0.30
    RANK_CONSTANT = 60
    LYRIC_INTENT = re.compile(r"\b(?:lyric|lyrics|song|sing|singing)\b|歌词|歌詞|唱歌|歌曲", re.IGNORECASE)

    def __init__(
        self,
        repository: LibraryRepository,
        moment_index: PersistentMomentIndex,
        *,
        reranker: Callable[[str, Iterable[str]], list[float]] | None = None,
        load_default_reranker: bool = True,
    ) -> None:
        self.repository = repository
        self.index = moment_index
        self.fts_path = self.index.root / "moments_fts.db"
        self.reranker = reranker
        self.load_default_reranker = load_default_reranker
        self._reranker_loaded = reranker is not None or not load_default_reranker

    def rebuild(self) -> int:
        count = self.index.rebuild()
        self.rebuild_lexical()
        return count

    def rebuild_lexical(self) -> int:
        rows = self.index.representations()
        with closing(sqlite3.connect(self.fts_path)) as connection:
            with connection:
                connection.execute("DROP TABLE IF EXISTS moments_fts")
                connection.execute(
                    "CREATE VIRTUAL TABLE moments_fts USING fts5("
                    "representation_id UNINDEXED, parent_moment_id UNINDEXED, representation_type UNINDEXED, text, tokenize='unicode61')"
                )
                connection.executemany(
                    "INSERT INTO moments_fts(representation_id, parent_moment_id, representation_type, text) VALUES (?, ?, ?, ?)",
                    [(row.representation_id, row.parent_moment_id, row.representation_type, row.text) for row in rows],
                )
        return len(rows)

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        candidate_k: int = 50,
        dense_k: int = 128,
        fts_k: int = 128,
        scope: SearchScope = SearchScope.ENTIRE_LIBRARY,
        creator_id: str | None = None,
        recording_id: str | None = None,
    ) -> list[SearchResult]:
        self._validate_scope(scope, creator_id, recording_id)
        rows = {row.moment_id: row for row in self.index.rows()}
        semantic_error = None
        try:
            dense = self.index.search(query, top_k=dense_k, creator_id=creator_id, recording_id=recording_id)
            if self.LYRIC_INTENT.search(query):
                lyric_dense = self.index.search(
                    query,
                    top_k=min(64, dense_k),
                    creator_id=creator_id,
                    recording_id=recording_id,
                    representation_types={"BACKGROUND_LYRICS"},
                )
                by_moment = {item.moment_id: item for item in dense}
                for item in lyric_dense:
                    # An explicit lyric query selects the classified lyric
                    # field for diagnostics/ranking even when the same parent
                    # has a marginally higher generic passage hit.
                    by_moment[item.moment_id] = item
                dense = list(by_moment.values())
                dense.sort(key=lambda item: (item.representation_type == "BACKGROUND_LYRICS", item.score), reverse=True)
        except EmbeddingModelUnavailable as exc:
            dense = []
            semantic_error = str(exc)
            logging.getLogger(__name__).warning("Semantic embedding model unavailable. Using lexical retrieval only: %s", exc)
        allowed_moment_ids = {
            moment_id
            for moment_id, row in rows.items()
            if self._allowed(row, scope, creator_id, recording_id)
        }
        lexical = self._lexical_search(query, fts_k, allowed_moment_ids)
        combined: dict[str, float] = {}
        diagnostics: dict[str, dict] = {}
        rerank_text: dict[str, str] = {}
        for rank, hit in enumerate(dense, start=1):
            representation_adjustment = 0.0
            if hit.representation_type == "BACKGROUND_LYRICS":
                representation_adjustment = 0.05 if self.LYRIC_INTENT.search(query) else -0.004
            elif hit.representation_type == "CORRECTED_SPEECH":
                representation_adjustment = 0.003
            combined[hit.moment_id] = combined.get(hit.moment_id, 0.0) + 1.0 / (60 + rank) + representation_adjustment
            diagnostics.setdefault(hit.moment_id, {}).update({
                "dense_rank": rank,
                "dense_score": float(hit.score),
                "winning_representation_id": hit.representation_id,
                "winning_representation_type": hit.representation_type,
                "winning_representation_excerpt": hit.excerpt,
                "representation_dense_rank": hit.representation_rank,
                "second_representation_score": hit.second_hit_score,
                "representation_adjustment": representation_adjustment,
            })
            rerank_text[hit.moment_id] = hit.excerpt
        for rank, lexical_hit in enumerate(lexical, start=1):
            moment_id = lexical_hit[0]
            combined[moment_id] = combined.get(moment_id, 0.0) + 1.0 / (60 + rank)
            details = diagnostics.setdefault(moment_id, {})
            details["fts_rank"] = rank
            details["fts_representation_id"] = lexical_hit[1]
            details["fts_representation_type"] = lexical_hit[2]
            rerank_text.setdefault(moment_id, lexical_hit[3])
        candidates = []
        for moment_id, score in combined.items():
            row = rows.get(moment_id)
            if row is None or not self._allowed(row, scope, creator_id, recording_id):
                continue
            diagnostics.setdefault(moment_id, {})["fusion_score"] = float(score)
            candidates.append((row, score, rerank_text.get(moment_id, row.summary or row.search_text[:500])))
        candidates.sort(key=lambda item: item[1], reverse=True)
        candidates = candidates[:candidate_k]
        reranker = self._get_reranker()
        if reranker and candidates:
            scores = reranker(query, [text for _, _, text in candidates])
            fusion_rank = {row.moment_id: rank for rank, (row, _, _) in enumerate(candidates, 1)}
            rerank_order = sorted(range(len(candidates)), key=lambda index: float(scores[index]), reverse=True)
            rerank_rank = {candidates[index][0].moment_id: rank for rank, index in enumerate(rerank_order, 1)}
            blended = []
            for (row, _, text), raw_score in zip(candidates, scores):
                base_rank = fusion_rank[row.moment_id]
                model_rank = rerank_rank[row.moment_id]
                final_score = (
                    self.FUSION_RANK_WEIGHT / (self.RANK_CONSTANT + base_rank)
                    + self.RERANK_WEIGHT / (self.RANK_CONSTANT + model_rank)
                )
                diagnostics.setdefault(row.moment_id, {}).update({
                    "reranker_score": float(raw_score),
                    "fusion_rank": base_rank,
                    "reranker_rank": model_rank,
                    "blended_rank_score": final_score,
                })
                blended.append((row, final_score, text))
            candidates = sorted(blended, key=lambda item: item[1], reverse=True)
        preference_creator_id = creator_id
        if preference_creator_id is None and recording_id:
            recording = self.repository.get_recording(recording_id)
            preference_creator_id = recording.creator_id if recording is not None else None
        candidates = self._apply_explicit_preferences(candidates, preference_creator_id)
        results = []
        for rank, (row, score, _) in enumerate(candidates[:top_k], 1):
            debug = dict(diagnostics.get(row.moment_id, {}))
            debug.update({"final_rank": rank, "semantic_error": semantic_error})
            results.append(self._result(row, score, debug))
        return results

    def runtime_metadata(self) -> dict:
        try:
            metadata = self.index.runtime_metadata()
        except EmbeddingModelUnavailable as exc:
            metadata = {
                "embedding_backend": None,
                "embedding_model": self.index.model_name,
                "embedding_dimension": None,
                "embedding_device": None,
                "retrieval_mode": "DEGRADED_FTS_ONLY",
                "embedding_error": str(exc),
            }
        reranker = self._get_reranker()
        metadata.update({
            "reranker_backend": type(reranker).__name__ if reranker else None,
            "reranker_model": getattr(reranker, "model_name", None),
            "reranker_device": getattr(reranker, "device", None),
            "reranker_enabled": reranker is not None,
        })
        return metadata

    def _lexical_search(
        self,
        query: str,
        limit: int,
        allowed_moment_ids: set[str] | None = None,
    ) -> list[tuple[str, str, str, str]]:
        if not self.fts_path.is_file() or not query.strip():
            return []
        terms = self._lexical_terms(query)
        if not terms:
            return []
        expression = " OR ".join(f'"{term}"' for term in terms)
        fetch_limit = limit if allowed_moment_ids is None else max(limit, limit * 4)
        with closing(sqlite3.connect(self.fts_path)) as connection:
            rows = connection.execute(
                "SELECT parent_moment_id, representation_id, representation_type, text "
                "FROM moments_fts WHERE moments_fts MATCH ? ORDER BY bm25(moments_fts) LIMIT ?",
                (expression, fetch_limit),
            ).fetchall()
        hits, seen = [], set()
        for row in rows:
            moment_id = str(row[0])
            if allowed_moment_ids is not None and moment_id not in allowed_moment_ids:
                continue
            if moment_id in seen:
                continue
            seen.add(moment_id)
            hits.append((moment_id, str(row[1]), str(row[2]), str(row[3])[:500]))
            if len(hits) >= limit:
                break
        return hits

    @staticmethod
    def _lexical_terms(query: str) -> list[str]:
        return [
            term
            for term in re.findall(r"[\w\u3400-\u9fff]+", query.casefold())
            if term not in _QUERY_STOPWORDS
        ]

    def _get_reranker(self):
        if not self._reranker_loaded:
            self.reranker = local_cross_encoder()
            self._reranker_loaded = True
        return self.reranker

    def _apply_explicit_preferences(self, candidates, creator_id: str | None):
        preferences = self.repository.list_preferences(creator_id)
        adjusted = []
        for row, score, rerank_text in candidates:
            text = rerank_text.casefold()
            value = score
            for preference in preferences:
                raw = preference.text.casefold()
                keywords = [
                    token
                    for token in re.findall(r"[a-z0-9]{3,}|[\u3400-\u9fff]{2,}", raw)
                    if token not in {"不要", "避免", "优先", "喜欢", "prefer", "avoid", "dont", "don't"}
                ]
                matches = any(keyword in text for keyword in keywords)
                if matches and any(marker in raw for marker in ("不要", "避免", "avoid", "don't", "dont")):
                    value -= 1.0
                elif matches and any(marker in raw for marker in ("优先", "喜欢", "prefer")):
                    value += 0.25
            adjusted.append((row, value, rerank_text))
        return sorted(adjusted, key=lambda item: item[1], reverse=True)

    @staticmethod
    def _validate_scope(scope: SearchScope, creator_id: str | None, recording_id: str | None) -> None:
        if scope == SearchScope.CREATOR and not creator_id:
            raise ValueError("CREATOR scope requires creator_id")
        if scope in {SearchScope.RECORDING, SearchScope.LIVE_SESSION} and not recording_id:
            raise ValueError(f"{scope.value} scope requires recording_id")

    @staticmethod
    def _allowed(row: IndexedMoment, scope: SearchScope, creator_id: str | None, recording_id: str | None) -> bool:
        if creator_id and row.creator_id != creator_id:
            return False
        if recording_id and row.recording_id != recording_id:
            return False
        return scope != SearchScope.LIVE_SESSION or row.status == MomentStatus.PROVISIONAL.value

    def _result(self, row: IndexedMoment, score: float, debug: dict | None = None) -> SearchResult:
        moment = self.repository.get_moment(row.moment_id)
        recording = self.repository.get_recording(row.recording_id)
        if moment is None or recording is None:
            raise RuntimeError("Moment index points to missing Library state; rebuild the index")
        try:
            evidence = json.loads(moment.evidence_json)
        except json.JSONDecodeError:
            evidence = []
        return SearchResult(
            moment_id=moment.id,
            creator_id=moment.creator_id,
            recording_id=moment.recording_id,
            start_ms=moment.start_ms,
            end_ms=moment.end_ms,
            score=score,
            summary=moment.summary,
            transcript_excerpt=moment.transcript_text[:500],
            recording_title=recording.title,
            recorded_at=recording.started_at.isoformat() if recording.started_at else None,
            moment_status=moment.status.value,
            evidence=evidence,
            debug=debug or {},
        )
