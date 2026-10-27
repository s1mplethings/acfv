"""Emit representation-level diagnostics for the immutable retrieval set."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

from acfv.library import LibraryService
from acfv.ragstack.index.faiss_index import search as vector_search
from acfv.retrieval import PersistentMomentIndex
from acfv.retrieval.reranker import local_cross_encoder


def _terms(query: str) -> str:
    values = re.findall(r"[\w\u3400-\u9fff]+", query.casefold())
    return " OR ".join(f'"{value}"' for value in values)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--index-root", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    library = LibraryService(args.database)
    index = PersistentMomentIndex(library.repository, args.index_root)
    representations = index.representations()
    row_map = {row.row_id: row for row in representations}
    reranker = local_cross_encoder()
    encoder = index._encoder()
    maximum = int(getattr(getattr(encoder, "tokenizer", None), "model_max_length", 512) or 512)
    if maximum > 100_000:
        maximum = 512
    output = []
    for case in cases:
        query = case["query"]
        target_id = case["ground_truth"]["moment_id"]
        target = library.repository.get_moment(target_id)
        target_rows = [row for row in representations if row.parent_moment_id == target_id]
        row_ids, scores = vector_search(index._encode([query], query=True), len(representations), index.index_path, index.id_map_path, emb_cache_path=index.embedding_path)
        raw = [(rank, float(score), row_map.get(row_id)) for rank, (row_id, score) in enumerate(zip(row_ids, scores), 1)]
        target_dense = [(rank, score, row) for rank, score, row in raw if row and row.parent_moment_id == target_id]
        first_parent_rank = None
        seen = set()
        for _, _, row in raw:
            if row.parent_moment_id not in seen:
                seen.add(row.parent_moment_id)
                if row.parent_moment_id == target_id:
                    first_parent_rank = len(seen)
                    break
        fts_rep_rank = fts_parent_rank = None
        with sqlite3.connect(index.root / "moments_fts.db") as connection:
            fts = connection.execute("SELECT representation_id, parent_moment_id FROM moments_fts WHERE moments_fts MATCH ? ORDER BY bm25(moments_fts)", (_terms(query),)).fetchall()
        parent_seen = set()
        for rank, (representation_id, parent_id) in enumerate(fts, 1):
            if parent_id not in parent_seen:
                parent_seen.add(parent_id)
                if parent_id == target_id and fts_parent_rank is None:
                    fts_parent_rank = len(parent_seen)
            if parent_id == target_id and fts_rep_rank is None:
                fts_rep_rank = rank
        reranker_scores = reranker(query, [row.text for row in target_rows]) if reranker and target_rows else []
        token_count = len(encoder.tokenizer(target.transcript_text, truncation=False)["input_ids"]) if target and hasattr(encoder, "tokenizer") else None
        output.append({
            "case_id": case["case_id"], "query": query, "target_moment_id": target_id,
            "ground_truth_transcript": case["ground_truth"]["transcript_excerpt"],
            "parent_transcript": target.transcript_text if target else None,
            "representations": [
                {"representation_id": row.representation_id, "type": row.representation_type, "start_ms": row.start_ms, "end_ms": row.end_ms, "text": row.text,
                 "dense_rank": next((rank for rank, _, found in target_dense if found.row_id == row.row_id), None),
                 "dense_score": next((score for _, score, found in target_dense if found.row_id == row.row_id), None),
                 "reranker_score": float(score) if reranker_scores else None}
                for row, score in zip(target_rows, reranker_scores or [None] * len(target_rows))
            ],
            "target_passage_dense_rank": min((rank for rank, _, row in target_dense if row.representation_type == "PASSAGE"), default=None),
            "target_parent_dense_rank": first_parent_rank,
            "target_fts_representation_rank": fts_rep_rank,
            "target_fts_parent_rank": fts_parent_rank,
            "transcript_token_length": token_count,
            "model_max_length": maximum,
            "actual_model_token_count": min(token_count, maximum) if token_count is not None else None,
            "truncated": token_count > maximum if token_count is not None else None,
        })
        print(case["case_id"], first_parent_rank, fts_parent_rank, flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
