from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from .. import (
    DEFAULT_DB_PATH,
    DEFAULT_EMB_CACHE_PATH,
    DEFAULT_FAISS_INDEX_PATH,
    DEFAULT_ID_MAP_PATH,
)
from ..embeddings.encoder import load_encoder
from ..index.faiss_index import search
from ..preference.engine import rerank_clips_for_user
from ..storage import db as storage_db
from ..storage.models import Clip


def embed_query(text: str, model_name: str = "all-MiniLM-L6-v2"):
    encoder = load_encoder(model_name)
    return encoder([text])


def vector_search(
    query_emb,
    top_k: int = 50,
    index_path: Path = DEFAULT_FAISS_INDEX_PATH,
    id_map_path: Path = DEFAULT_ID_MAP_PATH,
    emb_cache_path: Path | None = DEFAULT_EMB_CACHE_PATH,
) -> Tuple[List[int], List[float]]:
    return search(query_emb, top_k, index_path, id_map_path, emb_cache_path=emb_cache_path)


def fetch_clips(
    clip_ids: List[int],
    db_path: Path = DEFAULT_DB_PATH,
) -> List[Clip]:
    return storage_db.get_clips(db_path, clip_ids)


def rag_retrieve(
    user_pref,
    query_text: str,
    top_k: int = 50,
    db_path: Path = DEFAULT_DB_PATH,
    index_path: Path = DEFAULT_FAISS_INDEX_PATH,
    id_map_path: Path = DEFAULT_ID_MAP_PATH,
    emb_cache_path: Path | None = DEFAULT_EMB_CACHE_PATH,
    model_name: str = "all-MiniLM-L6-v2",
) -> Tuple[List[Clip], List[float]]:
    query_emb = embed_query(query_text, model_name=model_name)
    clip_ids, scores = vector_search(
        query_emb, top_k=top_k, index_path=index_path, id_map_path=id_map_path, emb_cache_path=emb_cache_path
    )
    clips = fetch_clips(clip_ids, db_path=db_path)
    # Align scores with fetched clips order
    id_to_score = {cid: s for cid, s in zip(clip_ids, scores)}
    base_scores = [id_to_score.get(c.clip_id, 0.0) for c in clips]
    reranked_clips, reranked_scores = rerank_clips_for_user(user_pref, clips, base_scores)
    return reranked_clips, reranked_scores
