from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows DLL search-path behavior")
def test_creator_adaptive_v3_registers_conda_cuda_runtime(monkeypatch, tmp_path: Path) -> None:
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    module = importlib.import_module("run_creator_adaptive_v3")
    runtime = tmp_path / "Library" / "bin"
    runtime.mkdir(parents=True)
    handle = object()
    calls: list[str] = []
    monkeypatch.setattr(module.sys, "prefix", str(tmp_path))
    monkeypatch.setattr(module.os, "add_dll_directory", lambda value: calls.append(value) or handle)
    monkeypatch.setenv("PATH", "C:\\Windows")

    result = module.activate_windows_cuda_runtime()

    assert result is handle
    assert calls == [str(runtime)]
    assert module.os.environ["PATH"].split(module.os.pathsep)[0] == str(runtime)
