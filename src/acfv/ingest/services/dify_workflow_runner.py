"""High-level convenience wrappers around DifyClient for workflows.

Usage examples:
    from services.dify_workflow_runner import get_default_client, run_summary
    result = run_summary("需要总结的文本...")
    print(result)

These helpers assume environment variables:
  DIFY_BASE_URL, DIFY_API_KEY (required), optional DIFY_BACKUP_API_KEY

Summary backend:
  ACFV_SUMMARY_BACKEND=local|dify (default: local)
"""
from __future__ import annotations
import os
import json
from typing import Dict, Any, Generator, Iterable
from .dify_client import DifyClient, ChatMessageChunk, try_extract_json
from .local_summarizer import summarize_local, stream_summary_local

__all__ = [
    "get_default_client",
    "run_workflow_blocking",
    "run_workflow_stream",
    "run_summary",
    "stream_summary",
]

_CLIENT_CACHE: DifyClient | None = None

def get_default_client() -> DifyClient:
    global _CLIENT_CACHE
    if _CLIENT_CACHE is None:
        _CLIENT_CACHE = DifyClient()
    return _CLIENT_CACHE

def _summary_backend() -> str:
    backend = (os.getenv("ACFV_SUMMARY_BACKEND") or os.getenv("SUMMARY_BACKEND") or "local").strip().lower()
    return backend or "local"

# Generic wrappers

def run_workflow_blocking(inputs: Dict[str, Any], user: str = "default", **extra: Any) -> Dict[str, Any]:
    client = get_default_client()
    return client.run_workflow(inputs=inputs, user=user, **extra)

def run_workflow_stream(inputs: Dict[str, Any], user: str = "default", **extra: Any) -> Generator[ChatMessageChunk, None, None]:
    client = get_default_client()
    yield from client.stream_workflow(inputs=inputs, user=user, **extra)

# Opinionated business helpers

def run_summary(text: str, context: str = "") -> Dict[str, Any]:
    backend = _summary_backend()
    if backend in {"local", "hf", "transformers"}:
        try:
            return summarize_local(text, context=context)
        except Exception as exc:
            return {"summary_text": "", "raw_answer": "", "error": f"local_summary_failed: {exc}"}
    client = get_default_client()
    return client.summarize(text, extra_context=context)

def stream_summary(text: str, context: str = "") -> Iterable[str]:
    backend = _summary_backend()
    if backend in {"local", "hf", "transformers"}:
        for data in stream_summary_local(text, context=context):
            yield "[JSON]" + data
        return
    client = get_default_client()
    for chunk in client.stream_workflow(inputs={"user_query": text, "context": context}, user="summarizer"):
        # Attempt incremental JSON extraction else yield raw
        data = chunk.data
        parsed = try_extract_json(data)
        if parsed:
            yield "[JSON]" + json.dumps(parsed, ensure_ascii=False)
        else:
            yield data
