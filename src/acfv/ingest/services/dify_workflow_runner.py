"""High-level convenience wrappers around DifyClient for workflows.

Usage examples:
    from services.dify_workflow_runner import get_default_client, run_summary
    result = run_summary("需要总结的文本...")
    print(result)

These helpers assume environment variables:
  DIFY_BASE_URL, DIFY_API_KEY (required), optional DIFY_BACKUP_API_KEY
"""
from __future__ import annotations
import os
from typing import Dict, Any, Generator, Iterable
from .dify_client import DifyClient, ChatMessageChunk, try_extract_json

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

# Generic wrappers

def run_workflow_blocking(inputs: Dict[str, Any], user: str = "default", **extra: Any) -> Dict[str, Any]:
    client = get_default_client()
    return client.run_workflow(inputs=inputs, user=user, **extra)

def run_workflow_stream(inputs: Dict[str, Any], user: str = "default", **extra: Any) -> Generator[ChatMessageChunk, None, None]:
    client = get_default_client()
    yield from client.stream_workflow(inputs=inputs, user=user, **extra)

# Opinionated business helpers

def run_summary(text: str, context: str = "") -> Dict[str, Any]:
    client = get_default_client()
    return client.summarize(text, extra_context=context)

def stream_summary(text: str, context: str = "") -> Iterable[str]:
    client = get_default_client()
    for chunk in client.stream_workflow(inputs={"user_query": text, "context": context}, user="summarizer"):
        # Attempt incremental JSON extraction else yield raw
        data = chunk.data
        parsed = try_extract_json(data)
        if parsed:
            yield "[JSON]" + str(parsed)
        else:
            yield data
