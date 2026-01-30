from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from acfv.modular.contracts import ART_CHAT_LOG, ART_CHAT_SOURCE
from acfv.modular.types import ModuleContext, ModuleSpec
from acfv.processing.extract_chat import extract_chat

SCHEMA_VERSION = "1.0.0"


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
        return {ART_CHAT_LOG: {"schema_version": SCHEMA_VERSION, "chat_path": None, "messages": 0, "records": []}}

    work_dir = Path(ctx.store.run_dir) / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path = work_dir / "chat.json"

    try:
        extract_chat(chat_path, str(out_path))
        records = _read_json(out_path)
        if isinstance(records, dict) and "records" in records:
            records = records["records"]
        if not isinstance(records, list):
            records = []
        # 归一化排序（若有 timestamp）
        try:
            records = sorted(records, key=lambda r: float(r.get("timestamp", 0)))
        except Exception:
            pass
        messages = len(records)
        start_ts = None
        end_ts = None
        if records:
            start_ts = records[0].get("timestamp")
            end_ts = records[-1].get("timestamp")
        chat_payload = {
            "schema_version": SCHEMA_VERSION,
            "chat_path": str(out_path),
            "messages": messages,
            "start_time": start_ts,
            "end_time": end_ts,
            "records": records,
        }
    except Exception:
        chat_payload = {"schema_version": SCHEMA_VERSION, "chat_path": str(out_path), "messages": 0, "records": []}

    if ctx.progress:
        ctx.progress("chat_extract", 1, 1, "done")

    return {ART_CHAT_LOG: chat_payload}


spec = ModuleSpec(
    name="extract_chat",
    version="1",
    inputs=[ART_CHAT_SOURCE],
    outputs=[ART_CHAT_LOG],
    run=run,
    description="Parse chat source into normalized chat log JSON.",
    impl_path="src/acfv/processing/extract_chat.py",
)

__all__ = ["spec"]
