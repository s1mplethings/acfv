from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import pytest

from acfv.steps.llm_highlight.impl import run_llm_highlight
from acfv.steps.screen_detect.impl import run_screen_detect
from acfv.steps.screen_understanding.impl import run_screen_understanding


class _Cfg:
    def __init__(self, values: dict):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


def test_llm_highlight_passthrough_when_disabled():
    semantic_payload = {
        "schema_version": "1.0.0",
        "units": "ms",
        "segments": [
            {"start_ms": 1000, "end_ms": 5000, "score": 2.5, "rank": 1, "text": "debugging a python bug"}
        ],
        "policy": {"target_duration_ms": 4000},
    }
    with TemporaryDirectory() as tmp:
        payload = run_llm_highlight(
            semantic_segments_payload=semantic_payload,
            candidate_segments_payload={},
            transcript_payload={"segments": [{"start": 1.0, "end": 5.0, "text": "debugging a python bug"}]},
            chat_payload={"records": []},
            screen_payload={"timeline": []},
            video_emotion_payload=[],
            work_dir=Path(tmp),
            config_manager=_Cfg({"ENABLE_LLM_HIGHLIGHT": False}),
        )
    assert payload["segments"]
    assert payload["segments"][0]["highlight_type"] == "rule_based"
    assert payload["policy"]["source"] == "llm_highlight_passthrough"


def test_screen_understanding_disabled_without_video_runtime():
    with TemporaryDirectory() as tmp:
        payload = run_screen_understanding(
            screen_windows_payload={"windows": []},
            transcript_payload={"segments": []},
            work_dir=Path(tmp),
            config_manager=_Cfg({"ENABLE_SCREEN_UNDERSTANDING": False}),
        )
    assert payload["status"] == "disabled"


def test_screen_detect_safe_fallback_when_disabled():
    with TemporaryDirectory() as tmp:
        payload = run_screen_detect(
            video_path="missing.mp4",
            work_dir=Path(tmp),
            config_manager=_Cfg({"ENABLE_SCREEN_DETECT": False}),
        )
    assert payload["status"] == "disabled"


def test_llm_highlight_raises_when_api_required_but_missing_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    semantic_payload = {
        "schema_version": "1.0.0",
        "units": "ms",
        "segments": [
            {"start_ms": 1000, "end_ms": 5000, "score": 2.5, "rank": 1, "text": "debugging a python bug"}
        ],
        "policy": {"target_duration_ms": 4000},
    }
    with TemporaryDirectory() as tmp:
        with pytest.raises(RuntimeError, match="requires an enabled LLM provider"):
            run_llm_highlight(
                semantic_segments_payload=semantic_payload,
                candidate_segments_payload={},
                transcript_payload={"segments": [{"start": 1.0, "end": 5.0, "text": "debugging a python bug"}]},
                chat_payload={"records": []},
                screen_payload={"timeline": []},
                video_emotion_payload=[],
                work_dir=Path(tmp),
                config_manager=_Cfg({"ENABLE_LLM_HIGHLIGHT": True, "REQUIRE_LLM_API": True}),
            )


def test_llm_highlight_accepts_empty_api_result(monkeypatch):
    class _Client:
        available = True

        def complete_json(self, **kwargs):
            return {"segments": []}

    semantic_payload = {
        "schema_version": "1.0.0",
        "units": "ms",
        "segments": [
            {"start_ms": 1000, "end_ms": 5000, "score": 2.5, "rank": 1, "text": "debugging a python bug"}
        ],
        "policy": {"target_duration_ms": 4000},
    }
    monkeypatch.setattr("acfv.steps.llm_highlight.impl.get_default_client", lambda **kwargs: _Client())
    with TemporaryDirectory() as tmp:
        payload = run_llm_highlight(
            semantic_segments_payload=semantic_payload,
            candidate_segments_payload={},
            transcript_payload={"segments": [{"start": 1.0, "end": 5.0, "text": "debugging a python bug"}]},
            chat_payload={"records": []},
            screen_payload={"timeline": []},
            video_emotion_payload=[],
            work_dir=Path(tmp),
            config_manager=_Cfg({"ENABLE_LLM_HIGHLIGHT": True, "REQUIRE_LLM_API": True}),
        )
    assert payload["policy"]["source"] == "llm_highlight"
    assert payload["segments"] == []


def test_llm_highlight_ignores_integer_message_count_chat_payload(monkeypatch):
    class _Client:
        available = True

        def complete_json(self, **kwargs):
            return {"segments": []}

    semantic_payload = {
        "schema_version": "1.0.0",
        "units": "ms",
        "segments": [
            {"start_ms": 1000, "end_ms": 5000, "score": 2.5, "rank": 1, "text": "debugging a python bug"}
        ],
        "policy": {"target_duration_ms": 4000},
    }
    monkeypatch.setattr("acfv.steps.llm_highlight.impl.get_default_client", lambda **kwargs: _Client())
    with TemporaryDirectory() as tmp:
        payload = run_llm_highlight(
            semantic_segments_payload=semantic_payload,
            candidate_segments_payload={},
            transcript_payload={"segments": [{"start": 1.0, "end": 5.0, "text": "debugging a python bug"}]},
            chat_payload={"schema_version": "1.0.0", "messages": 7612, "records": []},
            screen_payload={"timeline": []},
            video_emotion_payload=[],
            work_dir=Path(tmp),
            config_manager=_Cfg({"ENABLE_LLM_HIGHLIGHT": True, "REQUIRE_LLM_API": True}),
        )
    assert payload["segments"] == []


def test_llm_highlight_uses_local_distill_and_user_preference(monkeypatch):
    captured = {"prompts": []}

    class _Client:
        def __init__(self, prefix):
            self.prefix = prefix
            self.available = True

        def complete_json(self, **kwargs):
            captured["prompts"].append((self.prefix, kwargs["user_prompt"]))
            if self.prefix == "LLM_LOCAL":
                return {
                    "candidates": [
                        {
                            "candidate_id": "cand_001",
                            "distilled_summary": "artist fixing layers in digital art workflow",
                            "interest_tags": ["digital art", "layer management"],
                            "chat_takeaway": "chat reacts to drawing workflow",
                            "screen_takeaway": "clip studio style canvas and layers",
                            "transcript_takeaway": "speaker notices same-layer issue",
                            "user_interest_fit": "matches creative process preference",
                        }
                    ]
                }
            return {
                "segments": [
                    {
                        "candidate_id": "cand_001",
                        "start": 1.0,
                        "end": 5.0,
                        "score": 8.6,
                        "highlight_type": "creative_problem_solving",
                        "summary": "fixing layer workflow during art stream",
                        "reason_tags": ["digital art", "problem solving"],
                        "why_highlight": "matches preference and has clear on-screen action",
                        "confidence": 0.88,
                    }
                ]
            }

    def _fake_client(**kwargs):
        return _Client(kwargs.get("prefix"))

    monkeypatch.setattr("acfv.steps.llm_highlight.impl.get_default_client", _fake_client)
    semantic_payload = {
        "schema_version": "1.0.0",
        "units": "ms",
        "segments": [
            {"start_ms": 1000, "end_ms": 5000, "score": 2.5, "rank": 1, "text": "debugging a python bug"}
        ],
        "policy": {"target_duration_ms": 4000},
    }
    with TemporaryDirectory() as tmp:
        payload = run_llm_highlight(
            semantic_segments_payload=semantic_payload,
            candidate_segments_payload={},
            transcript_payload={"segments": [{"start": 1.0, "end": 5.0, "text": "debugging a python bug"}]},
            chat_payload={"records": [{"timestamp": 2.0, "author": "u1", "message": "wow layers"}]},
            screen_payload={"timeline": [{"start": 1.0, "end": 5.0, "screen_type": "art_app", "activity": "painting"}]},
            video_emotion_payload=[],
            work_dir=Path(tmp),
            config_manager=_Cfg(
                {
                    "ENABLE_LLM_HIGHLIGHT": True,
                    "ENABLE_LLM_LOCAL_DISTILL": True,
                    "LLM_LOCAL_MODEL": "qwen2.5:7b-instruct",
                    "LLM_HIGHLIGHT_USER_PREFERENCE_PROMPT": "prefer creative workflows and layer fixes",
                }
            ),
        )
    assert payload["segments"][0]["highlight_type"] == "creative_problem_solving"
    api_prompt = [prompt for prefix, prompt in captured["prompts"] if prefix == "LLM_HIGHLIGHT"][0]
    assert "local_distill" in api_prompt
    assert "prefer creative workflows and layer fixes" in api_prompt


def test_llm_highlight_trims_to_target_segments(monkeypatch):
    class _Client:
        available = True

        def complete_json(self, **kwargs):
            return {
                "segments": [
                    {
                        "candidate_id": "cand_001",
                        "start": 1.0,
                        "end": 5.0,
                        "score": 9.0,
                        "highlight_type": "best",
                        "summary": "best one",
                        "reason_tags": ["best"],
                        "why_highlight": "best",
                        "confidence": 0.9,
                    },
                    {
                        "candidate_id": "cand_002",
                        "start": 6.0,
                        "end": 9.0,
                        "score": 8.0,
                        "highlight_type": "second",
                        "summary": "second one",
                        "reason_tags": ["second"],
                        "why_highlight": "second",
                        "confidence": 0.8,
                    },
                ]
            }

    monkeypatch.setattr("acfv.steps.llm_highlight.impl.get_default_client", lambda **kwargs: _Client())
    semantic_payload = {
        "schema_version": "1.0.0",
        "units": "ms",
        "segments": [
            {"start_ms": 1000, "end_ms": 5000, "score": 2.5, "rank": 1, "text": "a"},
            {"start_ms": 6000, "end_ms": 9000, "score": 2.0, "rank": 2, "text": "b"},
        ],
        "policy": {"target_duration_ms": 4000},
    }
    with TemporaryDirectory() as tmp:
        payload = run_llm_highlight(
            semantic_segments_payload=semantic_payload,
            candidate_segments_payload={},
            transcript_payload={"segments": []},
            chat_payload={"records": []},
            screen_payload={"timeline": []},
            video_emotion_payload=[],
            work_dir=Path(tmp),
            config_manager=_Cfg({"ENABLE_LLM_HIGHLIGHT": True, "ENABLE_LLM_LOCAL_DISTILL": False}),
            target_segments_override=1,
        )
    assert len(payload["segments"]) == 1
    assert payload["policy"]["target_segments"] == 1


def test_screen_understanding_raises_when_api_required_but_missing_key():
    with TemporaryDirectory() as tmp:
        frame = Path(tmp) / "frame.jpg"
        frame.write_bytes(b"fake-jpeg")
        with pytest.raises(RuntimeError, match="requires API LLM/VLM"):
            run_screen_understanding(
                screen_windows_payload={
                    "windows": [
                        {
                            "start": 1.0,
                            "end": 5.0,
                            "frame_paths": [str(frame)],
                            "ocr_text_hint": "github pull request",
                        }
                    ]
                },
                transcript_payload={"segments": []},
                work_dir=Path(tmp),
                config_manager=_Cfg({"ENABLE_SCREEN_UNDERSTANDING": True, "REQUIRE_LLM_API": True}),
            )
