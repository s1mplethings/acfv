from __future__ import annotations

import json
from pathlib import Path

from acfv.enhance.tts import service


def test_normalize_prosody():
    assert service._normalize_prosody("+5%") == "+5%"
    assert service._normalize_prosody("5") == "+5%"
    assert service._normalize_prosody("-3") == "-3%"
    assert service._normalize_prosody("bad") == "+0%"


def test_normalize_pitch():
    assert service._normalize_pitch("+0Hz") == "+0Hz"
    assert service._normalize_pitch("3") == "+3Hz"
    assert service._normalize_pitch("-2%") == "-2Hz"
    assert service._normalize_pitch("bad") == "+0Hz"


def test_speech_url_normalizes_trailing_slash():
    assert service._speech_url("http://127.0.0.1:8000/v1/") == "http://127.0.0.1:8000/v1/audio/speech"


def test_compare_tts_writes_report_with_partial_failure(monkeypatch, tmp_path: Path):
    def _fake_edge(*, text: str, output_path: Path, voice: str, rate: str, pitch: str) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"edge")
        return output_path

    def _fake_vibe(**kwargs):
        raise service.TTSError("vibe unavailable")

    monkeypatch.setattr(service, "synthesize_edge_tts", _fake_edge)
    monkeypatch.setattr(service, "synthesize_openai_compatible", _fake_vibe)

    result = service.compare_tts(
        text="hello world",
        out_dir=tmp_path / "tts_compare",
        config={},
    )

    assert result["current"]["ok"] is True
    assert result["vibevoice"]["ok"] is False
    report_path = Path(result["report_path"])
    assert report_path.exists()
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["current"]["ok"] is True
    assert "error" in saved["vibevoice"]
