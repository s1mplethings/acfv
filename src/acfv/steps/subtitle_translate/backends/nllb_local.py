from __future__ import annotations

from .base import TranslatorBackend


class NllbLocalBackend(TranslatorBackend):
    name = "nllb"

    def __init__(self, *args, **kwargs):
        raise ImportError("NLLB backend not installed; requires transformers/ct2 setup")


__all__ = ["NllbLocalBackend"]
