from __future__ import annotations

from pathlib import Path

import pytest

from acfv.ingest import twitch
from acfv.providers import download as download_provider


def test_fetch_vod_returns_existing_local_path(tmp_path: Path):
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"x")
    got = twitch.fetch_vod(str(video), str(tmp_path / "work"))
    assert got == str(video)


def test_fetch_vod_raises_for_missing_local_path(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        twitch.fetch_vod(str(tmp_path / "missing.mp4"), str(tmp_path / "work"))


def test_fetch_vod_raises_for_non_twitch_url(tmp_path: Path):
    with pytest.raises(ValueError):
        twitch.fetch_vod("https://example.com/video.mp4", str(tmp_path / "work"))


def test_fetch_vod_downloads_twitch_vod(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    out_file = tmp_path / "work" / "12345.mp4"

    def fake_download(vod_id: str, workdir_path: Path):
        assert vod_id == "12345"
        assert workdir_path == tmp_path / "work"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(b"mp4")
        return out_file

    monkeypatch.setattr(download_provider, "download_twitch_vod", fake_download)

    got = twitch.fetch_vod("https://www.twitch.tv/videos/12345", str(tmp_path / "work"))
    assert got == str(out_file)


def test_fetch_vod_uses_streamlink_for_non_twitch_urls_when_configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    out_file = tmp_path / "work" / "streamlink_capture.mp4"

    class _Cfg:
        payload = {"providers": {"download": {"default": "streamlink"}}}

        def get(self, key, default=None):
            return default

    def fake_streamlink(url: str, workdir_path: Path, quality: str = "best"):
        assert url == "https://example.com/live.m3u8"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(b"mp4")
        return out_file

    monkeypatch.setattr(download_provider, "download_with_streamlink", fake_streamlink)

    got = twitch.fetch_vod("https://example.com/live.m3u8", str(tmp_path / "work"), config_manager=_Cfg())
    assert got == str(out_file)
