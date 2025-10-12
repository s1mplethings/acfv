# services/dify_backend_service.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, json, time
from typing import Dict, Any, Generator, Optional, Tuple
import requests

_DEFAULT_TIMEOUT = (5, 60)  # (connect, read)

def _join(base: str, path: str) -> str:
    base = base.rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    return base + path

def _auth_headers(api_key: str, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    h = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h

class _DifyClient:
    """极简 Dify 客户端：优先 workflow，失败回落 chat。"""
    def __init__(self, base_url: str, api_key: str, user_id: str = "gui-tester"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.user_id = user_id
        self.session = requests.Session()

    # ---- 探活 ----
    def get_meta(self) -> Tuple[bool, Dict[str, Any]]:
        url = _join(self.base_url, "/meta")
        try:
            r = self.session.get(url, headers=_auth_headers(self.api_key), timeout=_DEFAULT_TIMEOUT)
            ok = r.status_code == 200
            return ok, (r.json() if ok else {"status": r.status_code, "text": r.text})
        except Exception as e:
            return False, {"error": str(e), "url": url}

    # ---- 阻塞 ----
    def run_blocking(self, task: str, context: str = "") -> Tuple[str, Dict[str, Any]]:
        payload_wf = {
            "inputs": {"query": task, "context": context} if context else {"query": task},
            "response_mode": "blocking",
            "user": self.user_id,
        }
        url_wf = _join(self.base_url, "/workflows/run")
        t0 = time.time()
        try:
            r = self.session.post(url_wf, headers=_auth_headers(self.api_key), json=payload_wf, timeout=_DEFAULT_TIMEOUT)
            if r.status_code == 200:
                return "workflow", r.json()
            if r.status_code in (400, 404) and "not_workflow_app" in (r.text or "").lower():
                raise RuntimeError("fallback_to_chat")
        except Exception:
            pass  # fallback

        payload_chat = {
            "inputs": {},
            "query": task,
            "response_mode": "blocking",
            "user": self.user_id,
        }
        if context:
            payload_chat["inputs"] = {"context": context}

        url_chat = _join(self.base_url, "/chat-messages")
        r2 = self.session.post(url_chat, headers=_auth_headers(self.api_key), json=payload_chat, timeout=_DEFAULT_TIMEOUT)
        elapsed = time.time() - t0
        if r2.status_code != 200:
            raise RuntimeError(f"Dify error {r2.status_code}: {r2.text}")
        data = r2.json()
        return "chat", {"elapsed": elapsed, **data}

    # ---- 流式 ----
    def run_streaming(self, task: str, context: str = "") -> Generator[str, None, None]:
        try:
            for piece in self._stream_workflow(task, context):
                yield piece
            return
        except Exception:
            pass
        for piece in self._stream_chat(task, context):
            yield piece

    # ---- 私有：workflow 流 ----
    def _stream_workflow(self, task: str, context: str) -> Generator[str, None, None]:
        url = _join(self.base_url, "/workflows/run")
        payload = {
            "inputs": {"query": task, "context": context} if context else {"query": task},
            "response_mode": "streaming",
            "user": self.user_id,
        }
        with self.session.post(url, headers=_auth_headers(self.api_key), json=payload, stream=True, timeout=_DEFAULT_TIMEOUT) as r:
            if r.status_code != 200:
                raise RuntimeError(f"workflow stream error {r.status_code}: {r.text}")
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    s = line.decode("utf-8")
                except Exception:
                    continue
                if not s.startswith("data: "):
                    continue
                try:
                    data = json.loads(s[6:])
                except Exception:
                    continue
                d = data.get("data") or {}
                if isinstance(d, dict):
                    if d.get("answer"):
                        yield d["answer"]
                    elif d.get("text"):
                        yield d["text"]

    # ---- 私有：chat 流 ----
    def _stream_chat(self, task: str, context: str) -> Generator[str, None, None]:
        url = _join(self.base_url, "/chat-messages")
        payload = {
            "inputs": {"context": context} if context else {},
            "query": task,
            "response_mode": "streaming",
            "user": self.user_id,
        }
        with self.session.post(url, headers=_auth_headers(self.api_key), json=payload, stream=True, timeout=_DEFAULT_TIMEOUT) as r:
            if r.status_code != 200:
                raise RuntimeError(f"chat stream error {r.status_code}: {r.text}")
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    s = line.decode("utf-8")
                except Exception:
                    continue
                if not s.startswith("data: "):
                    continue
                try:
                    data = json.loads(s[6:])
                except Exception:
                    continue
                if data.get("answer"):
                    yield data["answer"]
                else:
                    d = data.get("data") or {}
                    if isinstance(d, dict) and d.get("answer"):
                        yield d["answer"]

class _Backend:
    """GUI 适配层"""
    def __init__(self):
        base = os.getenv("DIFY_BASE_URL", "http://localhost:5001/v1").strip()
        key = os.getenv("DIFY_API_KEY", "").strip()
        if not key:
            raise RuntimeError("缺少环境变量 DIFY_API_KEY")
        self.client = _DifyClient(base, key)
        self.mode = "auto"

    def preflight(self) -> Dict[str, Any]:
        ok, meta = self.client.get_meta()
        return {"base_url": self.client.base_url, "has_key": bool(self.client.api_key), "meta_ok": ok, "meta": meta}

    def run_blocking(self, task: str, context: str = "") -> Dict[str, Any]:
        t0 = time.time()
        mode, data = self.client.run_blocking(task, context)
        raw_answer = ""
        if mode == "chat":
            raw_answer = data.get("answer") or ""
            if not raw_answer:
                msg = data.get("message") or {}
                raw_answer = msg.get("answer") or ""
        meta = {"mode": mode, "elapsed": round(time.time() - t0, 3), "status": 200}
        return {"json": data, "raw_answer": raw_answer, "meta": meta}

    def run_streaming(self, task: str, context: str = "") -> Generator[str, None, None]:
        for piece in self.client.run_streaming(task, context):
            yield piece

_singleton: Optional[_Backend] = None
def get_backend() -> _Backend:
    global _singleton
    if _singleton is None:
        _singleton = _Backend()
    return _singleton
