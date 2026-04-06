from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from acfv.ingest import twitch


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
    calls: list[list[str]] = []
    out_file = tmp_path / "work" / "12345.mp4"

    def fake_cli(auto_install: bool = True):
        return "TwitchDownloaderCLI.exe"

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(b"mp4")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(twitch, "ensure_cli_on_path", fake_cli)
    monkeypatch.setattr(twitch.subprocess, "run", fake_run)

    got = twitch.fetch_vod("https://www.twitch.tv/videos/12345", str(tmp_path / "work"))
    assert got == str(out_file)
    assert calls and calls[0][0] == "TwitchDownloaderCLI.exe"
