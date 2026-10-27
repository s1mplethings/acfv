from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Callable, Iterable


DEFAULT_RERANKER_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"


class TransformersReranker:
    def __init__(self, model_name: str, *, device: str = "cpu") -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.model_name = model_name
        self.device = device
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name).to(device)
        self.model.eval()

    def __call__(self, query: str, texts: Iterable[str]) -> list[float]:
        values = list(texts)
        if not values:
            return []
        scores: list[float] = []
        with self.torch.inference_mode():
            for start in range(0, len(values), 16):
                pairs = [[query, text] for text in values[start : start + 16]]
                encoded = self.tokenizer(pairs, padding=True, truncation=True, max_length=512, return_tensors="pt")
                encoded = {key: value.to(self.device) for key, value in encoded.items()}
                logits = self.model(**encoded).logits.squeeze(-1)
                scores.extend(float(value) for value in logits.detach().cpu().reshape(-1))
        return scores


@lru_cache(maxsize=1)
def load_cross_encoder(model_name: str = DEFAULT_RERANKER_MODEL, device: str = "cpu"):
    try:
        return TransformersReranker(model_name, device=device)
    except Exception as exc:
        logging.getLogger(__name__).warning("Multilingual reranker unavailable; continuing without reranking: %s", exc)
        return None


def local_cross_encoder(model_name: str | None = None, *, device: str | None = None) -> Callable[[str, Iterable[str]], list[float]] | None:
    if os.getenv("ACFV_RERANKER_ENABLED", "1").strip().lower() in {"0", "false", "no", "off"}:
        return None
    resolved_model = model_name or os.getenv("ACFV_RERANKER_MODEL", DEFAULT_RERANKER_MODEL)
    resolved_device = device or os.getenv("ACFV_RERANKER_DEVICE", "cpu")
    model = load_cross_encoder(resolved_model, resolved_device)
    if model is None:
        return None
    return model
