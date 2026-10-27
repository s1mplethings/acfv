from __future__ import annotations

from types import SimpleNamespace

from acfv.modular.contracts import ART_CHAT_LOG, ART_TRANSCRIPT, ART_VIDEO, ART_VIDEO_EMOTION
from acfv.modular.plugins import analyze_segments as plugin


def test_pipeline_passes_cheap_analysis_and_rag_write_controls(monkeypatch, tmp_path):
    captured = {}

    def fake_analyze_data(*_args, **kwargs):
        captured.update(kwargs)
        return [{"start": 0.0, "end": 10.0, "score": 1.0, "text": "evidence"}]

    monkeypatch.setattr(plugin, "analyze_data", fake_analyze_data)
    monkeypatch.setattr(plugin, "processing_path", lambda name: tmp_path / name)
    ctx = SimpleNamespace(
        store=SimpleNamespace(run_dir=tmp_path / "run"),
        inputs={
            ART_CHAT_LOG: SimpleNamespace(payload=[]),
            ART_TRANSCRIPT: SimpleNamespace(
                payload={"segments": [{"start": 0.0, "end": 10.0, "text": "evidence"}]}
            ),
            ART_VIDEO: SimpleNamespace(payload={"path": str(tmp_path / "video.mp4")}),
            ART_VIDEO_EMOTION: SimpleNamespace(payload=[]),
        },
        params={
            "enable_audio_features": False,
            "rag_enable": False,
            "rag_write_analysis_ratings": False,
            "min_duration_sec": 5.0,
        },
        progress=None,
    )

    plugin.run(ctx)

    assert captured["config_overrides"] == {
        "ENABLE_AUDIO_FEATURES": False,
        "RAG_ENABLE": False,
        "RAG_WRITE_ANALYSIS_RATINGS": False,
    }
