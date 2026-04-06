from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from acfv.steps.transcribe_audio import impl


def test_check_ffmpeg_availability_uses_cache(monkeypatch):
    calls = {"count": 0}

    def fake_run(*args, **kwargs):
        calls["count"] += 1
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(impl.subprocess, "run", fake_run)
    impl._FFMPEG_AVAILABLE_CACHE = None
    assert impl.check_ffmpeg_availability() is True
    assert impl.check_ffmpeg_availability() is True
    assert calls["count"] == 1
    impl._FFMPEG_AVAILABLE_CACHE = None


def test_diagnostics_checkpoint_throttles_non_critical_events(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ACFV_TRANSCRIBE_CHECKPOINT_INTERVAL_SEC", "999")
    diag = impl._TranscribeDiagnostics(tmp_path, enabled=True)
    diag.event("heartbeat", value=1)
    diag.event("heartbeat", value=2)

    checkpoint = tmp_path / "transcribe_checkpoint.json"
    assert checkpoint.exists()
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert payload["stage"] == "heartbeat"
    assert payload["value"] == 1


def test_process_audio_segments_fallback_path(monkeypatch, tmp_path: Path):
    calls = {"count": 0}

    def fake_run(payload, work_dir):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("primary failed")
        return {"segments": [{"start": 0.0, "end": 1.0, "text": "ok", "speaker": "unk", "confidence": 0.5}]}

    monkeypatch.setattr(impl, "_guard_enabled", lambda: True)
    monkeypatch.setattr(impl, "_fallback_enabled", lambda: True)
    monkeypatch.setattr(impl, "_run_transcribe_subprocess", fake_run)

    output = tmp_path / "transcript.json"
    segments = impl.process_audio_segments(
        audio_path="dummy.mp4",
        output_file=str(output),
        segment_length=60,
    )
    assert len(segments) == 1
    assert calls["count"] == 2
