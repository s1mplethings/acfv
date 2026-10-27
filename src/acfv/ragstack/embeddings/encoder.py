from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Callable, Iterable

import numpy as np


DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-base"


class EmbeddingRuntimeMode(str, Enum):
    REAL_MODEL = "REAL_MODEL"
    DEGRADED_FTS_ONLY = "DEGRADED_FTS_ONLY"
    TEST_HASH = "TEST_HASH"


class EmbeddingModelUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class EmbeddingRuntimeInfo:
    mode: EmbeddingRuntimeMode
    model: str
    dimension: int | None
    device: str
    backend: str
    error: str | None = None


class TransformersEmbeddingEncoder:
    def __init__(self, model_name: str, *, device: str = "cpu", batch_size: int = 16) -> None:
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            # Long-lived GUI sessions may run the processing stack before the
            # retrieval model is first requested. Accelerate/Transformers can
            # then leave lazy initialization on the ``meta`` device, making a
            # later ``.to(cpu)`` fail. Retrieval requires materialized weights.
            self.model = AutoModel.from_pretrained(
                model_name,
                low_cpu_mem_usage=False,
            ).to(device)
        except Exception as exc:
            raise EmbeddingModelUnavailable(f"embedding model {model_name!r} unavailable: {exc}") from exc
        self.torch = torch
        self.model_name = model_name
        self.device = device
        self.batch_size = max(1, batch_size)
        self.dimension = int(getattr(self.model.config, "hidden_size", 0) or 0)
        self.model.eval()

    def __call__(self, texts: Iterable[str]) -> np.ndarray:
        return self.encode_passages(texts)

    def encode_queries(self, texts: Iterable[str]) -> np.ndarray:
        return self._encode([f"query: {text.strip()}" for text in texts])

    def encode_passages(self, texts: Iterable[str]) -> np.ndarray:
        return self._encode([f"passage: {text.strip()}" for text in texts])

    def _encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        batches = []
        with self.torch.inference_mode():
            for start in range(0, len(texts), self.batch_size):
                encoded = self.tokenizer(texts[start : start + self.batch_size], padding=True, truncation=True, max_length=512, return_tensors="pt")
                encoded = {key: value.to(self.device) for key, value in encoded.items()}
                output = self.model(**encoded).last_hidden_state
                mask = encoded["attention_mask"].unsqueeze(-1).expand(output.size()).float()
                pooled = (output * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
                pooled = self.torch.nn.functional.normalize(pooled, p=2, dim=1)
                batches.append(pooled.cpu().numpy().astype(np.float32))
        return np.concatenate(batches, axis=0)


class DeterministicHashEncoder:
    dimension = 384
    device = "cpu"

    def __call__(self, texts: Iterable[str]) -> np.ndarray:
        return self._encode(texts)

    encode_queries = __call__
    encode_passages = __call__

    def _encode(self, texts: Iterable[str]) -> np.ndarray:
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            rng = np.random.default_rng(int.from_bytes(digest[:8], "little", signed=False))
            vector = rng.standard_normal(self.dimension)
            vectors.append((vector / (np.linalg.norm(vector) + 1e-8)).astype(np.float32))
        return np.stack(vectors, axis=0)


@lru_cache(maxsize=4)
def _load_real_encoder(model_name: str, device: str) -> TransformersEmbeddingEncoder:
    return TransformersEmbeddingEncoder(model_name, device=device)


def load_encoder(model_name: str = DEFAULT_EMBEDDING_MODEL, *, device: str | None = None) -> Callable[[Iterable[str]], np.ndarray]:
    if os.getenv("ACFV_TEST_DETERMINISTIC_EMBEDDING", "").strip() == "1":
        return DeterministicHashEncoder()
    return _load_real_encoder(model_name, device or os.getenv("ACFV_EMBEDDING_DEVICE", "cpu"))


def runtime_info(encoder: Callable[[Iterable[str]], np.ndarray], model_name: str) -> EmbeddingRuntimeInfo:
    if isinstance(encoder, DeterministicHashEncoder):
        return EmbeddingRuntimeInfo(EmbeddingRuntimeMode.TEST_HASH, model_name, encoder.dimension, "cpu", "deterministic_sha256_hash")
    if isinstance(encoder, TransformersEmbeddingEncoder):
        return EmbeddingRuntimeInfo(EmbeddingRuntimeMode.REAL_MODEL, model_name, encoder.dimension, encoder.device, "transformers_mean_pooling")
    return EmbeddingRuntimeInfo(EmbeddingRuntimeMode.TEST_HASH, model_name, None, "test", "injected_test_encoder")


def config_hash(model_name: str, dimension: int | None, backend: str) -> str:
    return hashlib.sha256(f"v2|{model_name}|{dimension}|{backend}|e5-query-passage-prefix".encode("utf-8")).hexdigest()


def encode(texts: Iterable[str], model_name: str = DEFAULT_EMBEDDING_MODEL) -> np.ndarray:
    return load_encoder(model_name)(texts)
