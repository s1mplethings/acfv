from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "start_gpu_gui.ps1"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")


def run_resolver(*arguments: str, environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    if not POWERSHELL:
        pytest.skip("PowerShell is not available")
    command = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), *arguments, "-ResolveOnly"]
    return subprocess.run(command, capture_output=True, text=True, env=environment, check=False, timeout=20)


def clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("ACFV_PYTHON", None)
    environment.pop("CONDA_PREFIX", None)
    return environment


def test_launcher_explicit_parameter_wins_over_invalid_environment(tmp_path: Path):
    environment = clean_environment()
    environment["ACFV_PYTHON"] = str(tmp_path / "missing.exe")

    result = run_resolver("-PythonExecutable", sys.executable, environment=environment)

    assert result.returncode == 0, result.stderr
    assert str(Path(sys.executable).resolve()) in result.stdout


def test_launcher_accepts_legacy_python_path_alias():
    result = run_resolver("-PythonPath", sys.executable, environment=clean_environment())

    assert result.returncode == 0, result.stderr
    assert str(Path(sys.executable).resolve()) in result.stdout


def test_launcher_rejects_invalid_explicit_parameter(tmp_path: Path):
    result = run_resolver("-PythonExecutable", str(tmp_path / "missing.exe"), environment=clean_environment())

    assert result.returncode != 0
    assert "Explicit Python interpreter is not a file" in result.stderr


def test_launcher_uses_acfv_python():
    environment = clean_environment()
    environment["ACFV_PYTHON"] = sys.executable

    result = run_resolver(environment=environment)

    assert result.returncode == 0, result.stderr
    assert str(Path(sys.executable).resolve()) in result.stdout


def test_launcher_rejects_invalid_acfv_python(tmp_path: Path):
    environment = clean_environment()
    environment["ACFV_PYTHON"] = str(tmp_path / "missing.exe")

    result = run_resolver(environment=environment)

    assert result.returncode != 0
    assert "ACFV_PYTHON is not a valid Python interpreter" in result.stderr


@pytest.mark.skipif(Path(sys.executable).name.lower() != "python.exe", reason="Windows Conda resolution requires python.exe")
def test_launcher_uses_conda_prefix():
    environment = clean_environment()
    environment["CONDA_PREFIX"] = str(Path(sys.executable).parent)

    result = run_resolver(environment=environment)

    assert result.returncode == 0, result.stderr
    assert str(Path(sys.executable).resolve()) in result.stdout


def test_launcher_uses_path_python():
    environment = clean_environment()
    environment["PATH"] = str(Path(sys.executable).parent)

    result = run_resolver(environment=environment)

    assert result.returncode == 0, result.stderr
    assert str(Path(sys.executable).resolve()) in result.stdout


def test_launcher_reports_clear_error_when_python_is_unavailable(tmp_path: Path):
    environment = clean_environment()
    environment["PATH"] = str(tmp_path)

    result = run_resolver(environment=environment)

    assert result.returncode != 0
    assert "Python interpreter not found" in result.stderr
