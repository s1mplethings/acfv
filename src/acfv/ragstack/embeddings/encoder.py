from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Callable, Iterable, List

import numpy as np


@lru_cache(maxsize=2)
def _load_sentence_transformer(model_name: str):
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception:
        return None
    try:
        return SentenceTransformer(model_name)
    except Exception:
        return None


def load_encoder(model_name: str = "all-MiniLM-L6-v2") -> Callable[[Iterable[str]], np.ndarray]:
    st_model = _load_sentence_transformer(model_name)
    if st_model is not None:
        def encode(texts: Iterable[str]) -> np.ndarray:
            # sentence_transformers returns list; convert to float32 np array.
            return np.asarray(st_model.encode(list(texts), convert_to_numpy=True), dtype=np.float32)
        return encode

    def _hash_embed(text: str, dim: int = 384) -> np.ndarray:
        # Lightweight deterministic fallback: hash text into a pseudo-embedding.
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:8], "little", signed=False)
        rng = np.random.default_rng(seed)
        vec = rng.standard_normal(dim)
        norm = np.linalg.norm(vec) + 1e-8
        return (vec / norm).astype(np.float32)

    def encode(texts: Iterable[str]) -> np.ndarray:
        return np.stack([_hash_embed(t) for t in texts], axis=0)

    return encode


def encode(texts: Iterable[str], model_name: str = "all-MiniLM-L6-v2") -> np.ndarray:
    """Public helper to encode without manually loading the encoder."""
    return load_encoder(model_name)(texts)
