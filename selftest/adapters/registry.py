from __future__ import annotations

from pathlib import Path
from typing import List

from .base import Adapter

_ADAPTERS: List[Adapter] = []


def register(adapter: Adapter) -> None:
    _ADAPTERS.append(adapter)


def resolve(input_path: Path) -> Adapter:
    for adapter in _ADAPTERS:
        if adapter.match(input_path):
            return adapter
    raise RuntimeError(f"No adapter matched input: {input_path}")


def list_adapters() -> list[str]:
    return [adapter.name for adapter in _ADAPTERS]
