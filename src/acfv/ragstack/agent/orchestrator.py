from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Literal, Tuple

from .. import DEFAULT_DB_PATH, DEFAULT_FAISS_INDEX_PATH, DEFAULT_ID_MAP_PATH
from ..preference import engine as preference_engine
from ..preference import parser as preference_parser
from ..rag import context_builder, retrieval
from ..storage.db import get_user_pref, init_db, save_user_pref
from ..storage.models import Clip, UserPreference

Mode = Literal["auto", "search", "recommend"]


class Orchestrator:
    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        index_path: Path = DEFAULT_FAISS_INDEX_PATH,
        id_map_path: Path = DEFAULT_ID_MAP_PATH,
        emb_cache_path: Path | None = None,
    ):
        self.db_path = db_path
        self.index_path = index_path
        self.id_map_path = id_map_path
        self.emb_cache_path = emb_cache_path
        init_db(self.db_path)

    def _load_pref(self, user_id: str) -> UserPreference | None:
        return get_user_pref(self.db_path, user_id)

    def _ensure_pref(self, user_id: str) -> UserPreference:
        pref = self._load_pref(user_id)
        if pref:
            return pref
        pref = UserPreference(user_id=user_id, tag_weights={}, feature_prefs={})
        save_user_pref(self.db_path, pref)
        return pref

    def set_preference_text(self, user_id: str, text: str) -> UserPreference:
        parsed = preference_parser.parse_preference_text(text)
        pref = self._ensure_pref(user_id)
        pref = replace(pref)  # copy
        include = parsed.get("include_tags") or []
        exclude = parsed.get("exclude_tags") or []
        weights = dict(pref.tag_weights)
        for tag in include:
            weights[tag] = max(weights.get(tag, 0.0), 1.0)
        for tag in exclude:
            weights[tag] = min(weights.get(tag, 0.0), -1.0)
        pref.tag_weights = weights
        pref.feature_prefs = {
            "min_duration": parsed.get("min_duration"),
            "max_duration": parsed.get("max_duration"),
            "min_emotion": parsed.get("min_emotion"),
            "min_talk_ratio": parsed.get("min_talk_ratio"),
        }
        pref.raw_preference_text = text
        save_user_pref(self.db_path, pref)
        return pref

    def handle_query(
        self,
        user_id: str,
        query: str,
        mode: Mode = "auto",
        top_k: int = 30,
    ) -> Tuple[list[Clip], list[float], str]:
        pref = self._load_pref(user_id)
        chosen_mode: Mode = mode
        if mode == "auto":
            chosen_mode = "recommend" if not query or query.strip() == "" else "search"

        if chosen_mode == "recommend":
            # Simple recommend: use empty query but reuse preference scoring.
            query = query or "recommend"
        clips, scores = retrieval.rag_retrieve(
            pref,
            query,
            top_k=top_k,
            db_path=self.db_path,
            index_path=self.index_path,
            id_map_path=self.id_map_path,
            emb_cache_path=self.emb_cache_path,
        )
        ctx = context_builder.build_context(clips[:10])
        return clips, scores, ctx
