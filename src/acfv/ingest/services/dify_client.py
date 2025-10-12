"""Dify API Client

Minimal wrapper for interacting with a local Dify deployment.

Usage:
    from services.dify_client import DifyClient
    client = DifyClient(api_key="app-xxxxx")
    resp = client.chat("你好")
    print(resp.answer)

Environment variables respected:
    DIFY_BASE_URL  (default: http://localhost)
    DIFY_API_KEY   (if not passed explicitly)
    DIFY_TIMEOUT   (seconds, default 60)

Features:
    - Blocking chat message send
    - Streaming SSE chat (yield chunks)
    - Simple retry with backoff
    - Structured response dataclasses
    - Basic error wrapping

This keeps dependencies minimal (uses requests + sseclient if installed; otherwise manual SSE parse).
"""
from __future__ import annotations

import os
import time
import json
import logging
import threading
from dataclasses import dataclass
from typing import Dict, Any, Generator, Optional, List

import requests

try:
    # Optional dependency: sseclient-py for robust streaming parsing
    from sseclient import SSEClient  # type: ignore
    _HAS_SSE = True
except Exception:  # pragma: no cover
    _HAS_SSE = False


log = logging.getLogger(__name__)


@dataclass
class ChatMessageChunk:
    event: str
    data: str


@dataclass
class ChatMessageResponse:
    raw: Dict[str, Any]

    @property
    def answer(self) -> str:
        return self.raw.get("answer") or self.raw.get("message", {}).get("answer", "")

    @property
    def usage(self) -> Dict[str, Any]:
        return self.raw.get("metadata", {}).get("usage", {})


class DifyAPIError(RuntimeError):
    def __init__(self, status: int, body: Any):
        super().__init__(f"Dify API error {status}: {body}")
        self.status = status
        self.body = body


class DifyClient:
    """Primary client for Dify Service & Workflow APIs.

    Added features:
      - Workflow run helpers (blocking & streaming)
      - Fallback API key (second key used on recoverable errors)
      - JSON extraction utility
      - Simplified summarize() helper (expects workflow that returns JSON)
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: int = 2,
        backoff: float = 0.8,
        backup_api_key: Optional[str] = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("DIFY_BASE_URL") or "http://localhost:5001").rstrip("/")
        # 优先级：参数 > 环境变量 > .env文件 > dify_key.txt文件
        self.api_key = (
            api_key 
            or os.getenv("DIFY_API_KEY") 
            or self._load_from_env_file()
            or self._load_key_from_files()
        )
        if not self.api_key:
            raise ValueError(
                "DifyClient requires an API key. Set env DIFY_API_KEY, pass api_key, or create a file 'dify_key.txt'"
            )
        # optional fallback key
        self.backup_api_key = backup_api_key or os.getenv("DIFY_BACKUP_API_KEY")
        self.timeout = timeout or float(os.getenv("DIFY_TIMEOUT", "60"))
        self.max_retries = max_retries
        self.backoff = backoff
        self._session = requests.Session()
        self._default_headers = self._build_headers(self.api_key)

    def _build_headers(self, key: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _load_from_env_file(self) -> Optional[str]:
        """Try to read API key from .env file."""
        env_file = os.path.join(os.getcwd(), ".env")
        if os.path.isfile(env_file):
            try:
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("DIFY_API_KEY="):
                            return line.split("=", 1)[1]
            except Exception:
                pass
        return None

    def _load_key_from_files(self) -> Optional[str]:
        """Try to read API key from simple local files so GUI test works without env vars.

        Search order (first existing, first non-empty line used):
          ./dify_key.txt
          ./config/dify_key.txt
          ./.dify_key
        """
        candidates = [
            os.path.join(os.getcwd(), "dify_key.txt"),
            os.path.join(os.getcwd(), "config", "dify_key.txt"),
            os.path.join(os.getcwd(), ".dify_key"),
        ]
        for path in candidates:
            try:
                if os.path.isfile(path):
                    with open(path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#"):
                                return line
            except Exception:
                continue
        return None

    # -------------------- Public High-level Methods --------------------
    def chat(
        self,
        query: str,
        inputs: Optional[Dict[str, Any]] = None,
        user: str = "default",
        response_mode: str = "blocking",
        **extra: Any,
    ) -> ChatMessageResponse:
        payload = {
            "query": query,
            "inputs": inputs or {},
            "user": user,
            "response_mode": response_mode,
        }
        payload.update(extra)
        data = self._post_json("/v1/chat-messages", payload)
        return ChatMessageResponse(raw=data)

    def stream_chat(
        self,
        query: str,
        inputs: Optional[Dict[str, Any]] = None,
        user: str = "default",
        **extra: Any,
    ) -> Generator[ChatMessageChunk, None, None]:
        payload = {
            "query": query,
            "inputs": inputs or {},
            "user": user,
            "response_mode": "streaming",
        }
        payload.update(extra)
        yield from self._post_stream("/v1/chat-messages", payload)

    # -------------------- Low-level HTTP --------------------
    def _post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = self.base_url + path
        headers = self._default_headers
        tried_backup = False
        for attempt in range(self.max_retries + 1):
            try:
                if os.getenv("DIFY_DEBUG"):
                    log.debug("POST attempt %s %s payload_keys=%s", attempt, path, list(payload.keys()))
                resp = self._session.post(url, headers=headers, json=payload, timeout=self.timeout)
                if resp.status_code >= 400:
                    body = safe_json(resp)
                    # 400 参数类错误通常重试无意义，直接抛出
                    if resp.status_code == 400:
                        raise DifyAPIError(resp.status_code, body)
                    # If auth or server error and we have backup key not yet tried
                    if (
                        self.backup_api_key
                        and not tried_backup
                        and resp.status_code in (401, 403, 429, 500, 502, 503, 504)
                    ):
                        log.warning("Primary key failed with %s, switching to backup", resp.status_code)
                        headers = self._build_headers(self.backup_api_key)
                        tried_backup = True
                        continue
                    raise DifyAPIError(resp.status_code, body)
                return resp.json()  # success branch
            except (requests.RequestException, DifyAPIError) as e:
                # 400 或已到最大次数直接抛出
                if isinstance(e, DifyAPIError) and e.status == 400:
                    raise
                if attempt >= self.max_retries:
                    raise
                sleep_t = self.backoff * (2 ** attempt)
                log.warning("POST %s failed (%s), retrying in %.2fs", path, e, sleep_t)
                time.sleep(sleep_t)
        return {}

    def _post_stream(self, path: str, payload: Dict[str, Any]) -> Generator[ChatMessageChunk, None, None]:
        url = self.base_url + path
        headers = dict(self._default_headers)
        headers["Accept"] = "text/event-stream"
        tried_backup = False

        def _attempt(headers_local):
            if _HAS_SSE:
                resp = self._session.post(url, headers=headers_local, json=payload, stream=True, timeout=self.timeout)
                if resp.status_code >= 400:
                    raise DifyAPIError(resp.status_code, safe_json(resp))
                client = SSEClient(resp)
                for event in client.events():
                    if not event.data or event.data == "[DONE]":
                        continue
                    yield ChatMessageChunk(event=event.event, data=event.data)
            else:
                with self._session.post(url, headers=headers_local, json=payload, stream=True, timeout=self.timeout) as resp:
                    if resp.status_code >= 400:
                        raise DifyAPIError(resp.status_code, safe_json(resp))
                    buffer = []
                    for line in resp.iter_lines(decode_unicode=True):
                        if line is None:
                            continue
                        if not line.strip():
                            if buffer:
                                data_block = "\n".join(buffer)
                                evt, dat = parse_sse_block(data_block)
                                if dat and dat != "[DONE]":
                                    yield ChatMessageChunk(event=evt, data=dat)
                                buffer.clear()
                            continue
                        buffer.append(line)

        for attempt in range(self.max_retries + 1):
            try:
                yield from _attempt(headers)
                return
            except DifyAPIError as e:
                # 400 invalid_param 不重试
                if e.status == 400:
                    raise
                if (
                    self.backup_api_key
                    and not tried_backup
                    and e.status in (401, 403, 429, 500, 502, 503, 504)
                ):
                    log.warning("STREAM primary key failed %s switching to backup", e.status)
                    headers = self._build_headers(self.backup_api_key)
                    headers["Accept"] = "text/event-stream"
                    tried_backup = True
                    continue
                raise
            except (requests.RequestException) as e:
                if attempt >= self.max_retries:
                    raise
                sleep_t = self.backoff * (2 ** attempt)
                log.warning("STREAM %s failed (%s), retrying in %.2fs", path, e, sleep_t)
                time.sleep(sleep_t)

    # -------------------- Workflow APIs --------------------
    def run_workflow(
        self,
        inputs: Dict[str, Any],
        user: str = "default",
        response_mode: str = "blocking",
        **extra: Any,
    ) -> Dict[str, Any]:
        payload = {"inputs": inputs, "user": user, "response_mode": response_mode}
        payload.update(extra)
        return self._post_json("/v1/workflows/run", payload)

    def stream_workflow(
        self,
        inputs: Dict[str, Any],
        user: str = "default",
        **extra: Any,
    ) -> Generator[ChatMessageChunk, None, None]:
        payload = {"inputs": inputs, "user": user, "response_mode": "streaming"}
        payload.update(extra)
        yield from self._post_stream("/v1/workflows/streams", payload)

    # -------------------- High-level Helpers --------------------
    def summarize(self, text: str, extra_context: str = "") -> Dict[str, Any]:
        """Assumes workflow expects user_query & context and returns JSON in answer or outputs.
        Tries to parse JSON; if not JSON returns raw string under raw_answer.
        """
        inputs = {"user_query": text}
        if extra_context:
            inputs["context"] = extra_context
        result = self.run_workflow(inputs=inputs, user="summarizer")

        # Try to find JSON answer locations (depends on workflow). Strategy:
        # 1) Direct result['data']['outputs'] (if present)
        # 2) root keys answer / message
        # 3) Attempt JSON parse of any string blob
        parsed: Dict[str, Any] = {}
        try:
            outputs = result.get("data", {}).get("outputs") or result.get("outputs")
            if isinstance(outputs, dict):
                # pick first dict-like leaf with title or bullets
                for v in outputs.values():
                    if isinstance(v, str) and v.strip().startswith("{"):
                        parsed = try_extract_json(v)
                        if parsed:
                            break
                    if isinstance(v, dict) and ("title" in v or "bullets" in v):
                        parsed = v
                        break
            if not parsed:
                # maybe the top-level answer is embedded
                answer = result.get("answer") or result.get("message", {}).get("answer")
                if isinstance(answer, str):
                    parsed = try_extract_json(answer)
                elif isinstance(answer, dict):
                    parsed = answer
        except Exception:
            pass
        if not parsed:
            parsed = {"raw_answer": safe_compact_json(result)[:4000]}
        return parsed

    # -------------------- Utility --------------------
    def close(self):  # pragma: no cover
        try:
            self._session.close()
        except Exception:
            pass

    # -------------------- Misc Utilities --------------------
    def ping(self) -> Dict[str, Any]:
        """Ping Dify /v1/ping if available, returning status info.
        Some deployments may not expose this endpoint; handle gracefully.
        """
        url = self.base_url + "/v1/ping"
        t0 = time.time()
        try:
            resp = self._session.get(url, timeout=5)
            latency = round(time.time() - t0, 3)
            try:
                body = resp.json()
            except Exception:
                body = resp.text[:200]
            return {
                "ok": resp.status_code == 200,
                "status": resp.status_code,
                "latency_s": latency,
                "body": body,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}


from typing import Tuple


def parse_sse_block(block: str) -> Tuple[str, str]:
    event = "message"
    data_lines: List[str] = []
    for ln in block.splitlines():
        if ln.startswith(":"):
            continue
        if ln.startswith("event:"):
            event = ln[len("event:"):].strip()
        elif ln.startswith("data:"):
            data_lines.append(ln[len("data:"):].strip())
    return event, "\n".join(data_lines)


def safe_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return resp.text[:500]


def try_extract_json(text: str) -> Dict[str, Any]:
    """Extract the first top-level JSON object from a string; return {} if fail."""
    import re, json as _json
    if not text:
        return {}
    # naive scan for { ... }
    start_positions = [i for i, ch in enumerate(text) if ch == '{']
    for pos in start_positions[:5]:  # limit search
        brace = 0
        for j in range(pos, len(text)):
            if text[j] == '{':
                brace += 1
            elif text[j] == '}':
                brace -= 1
                if brace == 0:
                    snippet = text[pos:j+1]
                    try:
                        return _json.loads(snippet)
                    except Exception:
                        break
    return {}


def safe_compact_json(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(obj)


# Quick manual test when run directly
if __name__ == "__main__":  # pragma: no cover
    key = os.getenv("DIFY_API_KEY") or ""
    if not key:
        print("Set DIFY_API_KEY env var to test.")
    else:
        c = DifyClient(api_key=key)
        r = c.chat("你好，测试一下")
        print(r.answer)
