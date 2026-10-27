from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Tuple

import numpy as np

FAISS_AVAILABLE = False
try:
    import faiss  # type: ignore
    FAISS_AVAILABLE = True
except Exception:
    faiss = None  # type: ignore


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-8
    return vectors / norms


def build_index(
    embeddings: np.ndarray,
    clip_ids: Iterable[int],
    index_path: Path,
    id_map_path: Path,
    emb_cache_path: Path | None = None,
) -> None:
    embeddings = _normalize(np.asarray(embeddings, dtype=np.float32))
    id_array = np.asarray(list(clip_ids), dtype=np.int64)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    id_map_path.parent.mkdir(parents=True, exist_ok=True)
    if emb_cache_path:
        emb_cache_path.parent.mkdir(parents=True, exist_ok=True)

    if FAISS_AVAILABLE:
        index = faiss.IndexFlatIP(embeddings.shape[1])
        index.add(embeddings)
        faiss.write_index(index, str(index_path))
    else:
        # Fallback: persist embeddings for brute-force search.
        np.save(index_path.with_suffix(".npy"), embeddings)

    np.save(id_map_path, id_array)
    if emb_cache_path:
        np.save(emb_cache_path, embeddings)


def _load_embeddings(index_path: Path, emb_cache_path: Path | None = None) -> np.ndarray:
    if emb_cache_path and emb_cache_path.exists():
        return np.load(emb_cache_path)
    npy_path = index_path if index_path.suffix == ".npy" else index_path.with_suffix(".npy")
    return np.load(npy_path)


def search(
    query_emb: np.ndarray,
    top_k: int,
    index_path: Path,
    id_map_path: Path,
    emb_cache_path: Path | None = None,
) -> Tuple[List[int], List[float]]:
    query_emb = _normalize(np.asarray(query_emb, dtype=np.float32))
    id_array = np.load(id_map_path)

    if FAISS_AVAILABLE and index_path.exists():
        index = faiss.read_index(str(index_path))
        scores, idxs = index.search(query_emb, top_k)
    else:
        embeddings = _load_embeddings(index_path, emb_cache_path)
        scores = query_emb @ embeddings.T
        idxs = np.argpartition(-scores, kth=min(top_k, scores.shape[1] - 1), axis=1)[:, :top_k]
        # Re-sort each row by score descending for stability.
        for row in range(idxs.shape[0]):
            order = np.argsort(-scores[row, idxs[row]])
            idxs[row] = idxs[row, order]
            scores[row] = scores[row, idxs[row]]

    clip_ids: List[int] = []
    clip_scores: List[float] = []
    for i, score in zip(idxs[0], scores[0]):
        if i < len(id_array):
            clip_ids.append(int(id_array[i]))
            clip_scores.append(float(score))
    return clip_ids, clip_scores
