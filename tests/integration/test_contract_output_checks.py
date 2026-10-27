from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support import (
    REPO_ROOT,
    base_clip_config,
    install_fake_analyze,
    install_fake_transcribe_guard,
    run_clip_pipeline_for_test,
    run_contract_check,
)


pytestmark = pytest.mark.usefixtures("require_ffmpeg")


def test_contract_output_checks_validate_real_generated_artifacts(monkeypatch, sample_video_path, contract_run_dir):
    install_fake_transcribe_guard(monkeypatch)
    install_fake_analyze(monkeypatch)
    run_clip_pipeline_for_test(
        run_dir=contract_run_dir,
        video_path=sample_video_path,
        config=base_clip_config(),
    )
    result = run_contract_check(contract_run_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[contract_checks] PASS" in result.stdout
    assert (contract_run_dir / "work" / "selected_segments.json").exists()
    assert (contract_run_dir / "work" / "clips_manifest.json").exists()


def test_contract_output_checks_require_artifacts_in_empty_run_dir(tmp_path):
    missing_run_dir = tmp_path / "empty_run"
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "contract_checks.py"),
            "--run-dir",
            str(missing_run_dir),
            "--require-artifacts",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert result.returncode != 0
    assert "FAIL" in result.stdout


def test_contract_output_checks_keep_template_mode_without_explicit_run_dir(tmp_path):
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "contract_checks.py")],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert result.returncode == 0
    assert "no known artifact files found" in result.stdout
