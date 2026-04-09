from __future__ import annotations

from pathlib import Path

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
