from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from tests.support import ensure_sample_video, write_chat_log


@pytest.fixture
def require_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe required for clip workflow tests")


@pytest.fixture
def sample_video_path(tmp_path_factory) -> Path:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe required for sample video fixture")
    sample_dir = tmp_path_factory.mktemp("sample_video")
    return ensure_sample_video(sample_dir / "sample.mp4", duration_sec=10.0)


@pytest.fixture
def sample_chat_path(tmp_path) -> Path:
    return write_chat_log(tmp_path / "chat.json")


@pytest.fixture
def contract_run_dir(tmp_path) -> Path:
    explicit = os.environ.get("ACFV_CONTRACT_RUN_DIR", "").strip()
    if explicit:
        path = Path(explicit)
        path.mkdir(parents=True, exist_ok=True)
        return path
    return tmp_path / "contract_run"
