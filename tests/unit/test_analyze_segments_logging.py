from __future__ import annotations

from types import SimpleNamespace

from acfv.steps.analyze_segments import impl


def test_safe_console_text_replaces_unencodable_emoji():
    stream = SimpleNamespace(encoding="gbk")

    text = impl._safe_console_text("⚡超快特征提取", stream=stream)

    assert text != ""
    assert "超快特征提取" in text
    assert "\u26a1" not in text


def test_ultra_fast_parallel_extraction_sanitizes_tqdm_and_progress(monkeypatch):
    seen = {}

    class _Extractor(impl.UltraFastExtractor):
        def __init__(self):
            pass

        def batch_extract_features(self, batch):
            return [{"music_probability": 0.0, "loud_db": -30.0} for _ in batch]

    class _Bar:
        def update(self, _count):
            return None

        def close(self):
            return None

    monkeypatch.setattr(impl, "TQDM_AVAILABLE", True)
    monkeypatch.setattr(impl.sys, "stderr", SimpleNamespace(encoding="gbk"), raising=False)

    def fake_tqdm(*args, **kwargs):
        seen["desc"] = kwargs.get("desc")
        return _Bar()

    progress_calls = []
    monkeypatch.setattr(impl, "tqdm", fake_tqdm)

    result = impl.ultra_fast_parallel_extraction(
        _Extractor(),
        [{"start": 0.0, "end": 1.0, "text": "a"}],
        progress_callback=lambda stage, current, total, message: progress_calls.append((stage, current, total, message)),
    )

    assert len(result) == 1
    assert "\u26a1" not in seen["desc"]
    assert progress_calls
    assert "\u26a1" not in progress_calls[0][0]


def test_ultra_fast_parallel_extraction_tolerates_broken_tqdm_stream(monkeypatch):
    class _Extractor(impl.UltraFastExtractor):
        def __init__(self):
            pass

        def batch_extract_features(self, batch):
            return [{"music_probability": 0.0, "loud_db": -30.0} for _ in batch]

    class _BrokenBar:
        def update(self, _count):
            raise OSError(22, "Invalid argument")

        def close(self):
            raise OSError(22, "Invalid argument")

    monkeypatch.setattr(impl, "TQDM_AVAILABLE", True)
    monkeypatch.setattr(impl, "tqdm", lambda *args, **kwargs: _BrokenBar())

    result = impl.ultra_fast_parallel_extraction(
        _Extractor(),
        [
            {"start": 0.0, "end": 1.0, "text": "a"},
            {"start": 1.0, "end": 2.0, "text": "b"},
        ],
    )

    assert len(result) == 2
