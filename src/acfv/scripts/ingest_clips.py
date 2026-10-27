from __future__ import annotations

import argparse
import json
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
from acfv.ragstack.storage.models import Clip


def load_clips_from_jsonl(path: Path) -> List[Clip]:
    clips: List[Clip] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            clips.append(
                Clip(
                    clip_id=None,
                    video_id=data["video_id"],
                    start_sec=float(data["start_sec"]),
                    end_sec=float(data["end_sec"]),
                    duration=float(data.get("duration") or (float(data["end_sec"]) - float(data["start_sec"]))),
                    summary_text=data.get("summary_text"),
                    raw_text=data.get("raw_text"),
                    tags=data.get("tags") or [],
                    highlight_score=data.get("highlight_score"),
                    emotion_score=data.get("emotion_score"),
                    talk_ratio=data.get("talk_ratio"),
                    extra=data.get("extra") or {},
                )
            )
    return clips


def ingest(jsonl_path: Path, db_path: Path, index_path: Path, id_map_path: Path, emb_cache_path: Path | None, model_name: str):
    storage_db.init_db(db_path)
    clips = load_clips_from_jsonl(jsonl_path)
    encoder = load_encoder(model_name)

    texts = [c.summary_text or c.raw_text or "" for c in clips]
    embeddings = encoder(texts)

    clip_ids: List[int] = []
    for clip in clips:
        clip_id = storage_db.insert_clip(db_path, clip)
        clip.clip_id = clip_id
        clip_ids.append(clip_id)

    build_index(
        embeddings=np.asarray(embeddings, dtype="float32"),
        clip_ids=clip_ids,
        index_path=index_path,
        id_map_path=id_map_path,
        emb_cache_path=emb_cache_path,
    )
    print(f"Ingested {len(clip_ids)} clips into {db_path}")


def main():
    parser = argparse.ArgumentParser(description="Ingest clips and build vector index.")
    parser.add_argument("--input", type=Path, required=True, help="JSONL file with clips")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--index", type=Path, default=DEFAULT_FAISS_INDEX_PATH)
    parser.add_argument("--id-map", type=Path, default=DEFAULT_ID_MAP_PATH)
    parser.add_argument("--emb-cache", type=Path, default=DEFAULT_EMB_CACHE_PATH)
    parser.add_argument("--model", type=str, default="all-MiniLM-L6-v2")
    args = parser.parse_args()
    ingest(args.input, args.db, args.index, args.id_map, args.emb_cache, args.model)


if __name__ == "__main__":
    main()
