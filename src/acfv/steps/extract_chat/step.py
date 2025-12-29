from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from acfv.modular.contracts import ART_CHAT_LOG, ART_CHAT_SOURCE
from acfv.modular.types import ModuleContext
from acfv.processing.extract_chat import extract_chat


def _read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def run(ctx: ModuleContext) -> Dict[str, Any]:
    source = ctx.inputs[ART_CHAT_SOURCE].payload or {}
    if isinstance(source, dict):
        chat_path = source.get("path") or ""
    else:
        chat_path = str(source)

    if ctx.progress:
        ctx.progress("chat_extract", 0, 1, "start")

    if not chat_path or not os.path.exists(chat_path):
        if ctx.progress:
            ctx.progress("chat_extract", 1, 1, "no chat")
        return {ART_CHAT_LOG: []}

    work_dir = Path(ctx.store.run_dir) / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path = work_dir / "chat.json"

    try:
        extract_chat(chat_path, str(out_path))
        chat_payload = _read_json(out_path)
    except Exception:
        chat_payload = []

    if ctx.progress:
        ctx.progress("chat_extract", 1, 1, "done")

    return {ART_CHAT_LOG: chat_payload}


__all__ = ["run"]
