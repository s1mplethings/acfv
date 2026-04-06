from __future__ import annotations

from .base import TranslatorBackend


class SeamlessLocalBackend(TranslatorBackend):
    name = "seamless"

    def __init__(self, *args, **kwargs):
        raise ImportError("Seamless backend not installed; requires transformers setup")


__all__ = ["SeamlessLocalBackend"]
