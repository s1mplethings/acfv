from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

import numpy as np

from acfv.ragstack import (
    DEFAULT_DB_PATH,
    DEFAULT_EMB_CACHE_PATH,
    DEFAULT_FAISS_INDEX_PATH,
    DEFAULT_ID_MAP_PATH,
)
from acfv.ragstack.embeddings.encoder import load_encoder
from acfv.ragstack.index.faiss_index import build_index
from acfv.ragstack.storage import db as storage_db


def rebuild(db_path: Path, index_path: Path, id_map_path: Path, emb_cache_path: Path | None, model_name: str):
    storage_db.init_db(db_path)
    with storage_db._connect(db_path) as conn:  # type: ignore
        rows = conn.execute("SELECT clip_id, summary_text, raw_text FROM clips").fetchall()

    clip_ids: List[int] = [row["clip_id"] for row in rows]
    texts = [(row["summary_text"] or row["raw_text"] or "") for row in rows]

    encoder = load_encoder(model_name)
    embeddings = encoder(texts)
    build_index(
        embeddings=np.asarray(embeddings, dtype="float32"),
        clip_ids=clip_ids,
        index_path=index_path,
        id_map_path=id_map_path,
        emb_cache_path=emb_cache_path,
    )
    print(f"Rebuilt index with {len(clip_ids)} clips")


def main():
    parser = argparse.ArgumentParser(description="Rebuild vector index from existing clips.db")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--index", type=Path, default=DEFAULT_FAISS_INDEX_PATH)
    parser.add_argument("--id-map", type=Path, default=DEFAULT_ID_MAP_PATH)
    parser.add_argument("--emb-cache", type=Path, default=DEFAULT_EMB_CACHE_PATH)
    parser.add_argument("--model", type=str, default="all-MiniLM-L6-v2")
    args = parser.parse_args()
    rebuild(args.db, args.index, args.id_map, args.emb_cache, args.model)


if __name__ == "__main__":
    main()
