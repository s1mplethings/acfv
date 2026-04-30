from __future__ import annotations

from pathlib import Path
import time

import pytest
from acfv.cli import gui


def test_derive_conda_root_from_base_python():
    root = gui._derive_conda_root(Path(r"D:\anaconda\python.exe"))
    assert root == Path(r"D:\anaconda")


def test_derive_conda_root_from_env_python():
    root = gui._derive_conda_root(Path(r"D:\anaconda\envs\clip\python.exe"))
    assert root == Path(r"D:\anaconda")


def test_pick_better_python_prefers_cuda_and_faster_whisper(monkeypatch):
    current_python = Path(r"D:\anaconda\python.exe")
    current_info = {
        "PyQt5": True,
        "faster_whisper": False,
        "openai_whisper": True,
        "cuda": False,
    }
    clip_python = Path(r"D:\anaconda\envs\clip\python.exe")
    cpu_python = Path(r"D:\anaconda\envs\subtitle\python.exe")

    monkeypatch.setattr(gui, "_candidate_python_paths", lambda _: [cpu_python, clip_python])

    def _fake_probe(path: Path):
        if path == clip_python:
            return {
                "PyQt5": True,
                "faster_whisper": True,
                "openai_whisper": True,
                "cuda": True,
            }
        return {
            "PyQt5": True,
            "faster_whisper": False,
            "openai_whisper": True,
            "cuda": False,
        }

    monkeypatch.setattr(gui, "_probe_python_env", _fake_probe)
    assert gui._pick_better_python(current_python, current_info) == clip_python


def test_gui_launch_disables_start_in_tray(monkeypatch):
    monkeypatch.delenv(gui._DISABLE_START_IN_TRAY, raising=False)
    monkeypatch.setattr(gui, "_maybe_relaunch_in_better_env", lambda: False)

    called = {}

    def _fake_launch_gui():
        called["launched"] = True

    import builtins

    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "acfv.app.gui":
            class _Module:
                launch_gui = staticmethod(_fake_launch_gui)
            return _Module()
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    gui._launch()

    assert called["launched"] is True
    assert gui.os.environ[gui._DISABLE_START_IN_TRAY] == "1"


def test_twitch_downloader_init_is_lazy(monkeypatch):
    from acfv.steps.twitch_downloader.impl import TwitchDownloader

    called = {"count": 0}

    def _unexpected_ensure(*args, **kwargs):
        called["count"] += 1
        raise AssertionError("GUI startup should not auto-install TwitchDownloaderCLI")

    monkeypatch.setattr("acfv.steps.twitch_downloader.impl.ensure_cli_on_path", _unexpected_ensure)

    downloader = TwitchDownloader(config_manager=None)

    assert downloader.cli_path is None
    assert called["count"] == 0


def test_rag_preference_widget_defers_db_init_until_event_loop(monkeypatch):
    pytest.importorskip("PyQt5.QtCore")
    from PyQt5 import QtWidgets
    from acfv.ui.tabs.rag_pref_tab import RAGPreferenceWidget

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    calls: list[str] = []

    def _fake_init_db(self):
        calls.append("init_db")

    def _fake_refresh_summary(self):
        calls.append("refresh_summary")

    monkeypatch.setattr(RAGPreferenceWidget, "_init_db", _fake_init_db)
    monkeypatch.setattr(RAGPreferenceWidget, "refresh_summary", _fake_refresh_summary)

    class _Config:
        def __init__(self):
            self.values = {}

        def get(self, key, default=None):
            return self.values.get(key, default)

        def set(self, key, value, persist=True):
            self.values[key] = value

    widget = RAGPreferenceWidget(_Config())
    assert calls == []

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and len(calls) < 2:
        app.processEvents()
        time.sleep(0.01)

    assert calls == ["init_db", "refresh_summary"]
    widget.deleteLater()
