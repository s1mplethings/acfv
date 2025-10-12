import os
import types
import pytest

from services.dify_backend_service import DifyBackend

class DummyClient:
    def __init__(self, mode="workflow"):
        self.api_key = "app-dummy"
        self.mode = mode
        self.base_url = "http://localhost:5001"
        self.backup_api_key = None

    # workflow style
    def run_workflow(self, inputs, user="test", response_mode="blocking"):
        # Simulate returning structured outputs
        return {
            "data": {
                "outputs": {
                    "summary": {"title": "Test", "bullets": [inputs.get("user_query", "")]}
                }
            }
        }

    def stream_workflow(self, inputs, user="test"):
        yield types.SimpleNamespace(data="Hello ")
        yield types.SimpleNamespace(data="World")

    # chat style
    def chat(self, message, user="test", response_mode="blocking"):
        class Obj:  # mimic ChatMessageResponse
            answer = f"Echo: {message}"[:100]
        return Obj()

    def stream_chat(self, message, user="test"):
        yield types.SimpleNamespace(data="Chat ")
        yield types.SimpleNamespace(data="Stream")

    def ping(self):
        return {"ok": True, "status": 200}

@pytest.mark.parametrize("force_mode", ["workflow", "chat"]) 
def test_blocking_modes(monkeypatch, force_mode):
    monkeypatch.setenv("DIFY_FORCE_MODE", force_mode)
    backend = DifyBackend(client=DummyClient())
    out = backend.run_blocking("测试一下", context="上下文")
    assert "meta" in out
    assert out["meta"]["mode"] == force_mode
    assert isinstance(out.get("raw_answer"), str)


def test_streaming_workflow(monkeypatch):
    monkeypatch.setenv("DIFY_FORCE_MODE", "workflow")
    backend = DifyBackend(client=DummyClient())
    pieces = list(backend.run_streaming("hello"))
    assert any("END" in p for p in pieces)
    assert "Hello" in "".join(pieces)


def test_streaming_chat(monkeypatch):
    monkeypatch.setenv("DIFY_FORCE_MODE", "chat")
    backend = DifyBackend(client=DummyClient())
    pieces = list(backend.run_streaming("hello"))
    combined = "".join(pieces)
    assert "Chat" in combined and "Stream" in combined


def test_preflight(monkeypatch):
    monkeypatch.setenv("DIFY_FORCE_MODE", "workflow")
    backend = DifyBackend(client=DummyClient())
    info = backend.preflight()
    # preflight uses real HTTP; in this dummy test we just assert shape keys exist
    assert "base_url" in info
    assert "ping" in info
    assert "mode" in info
