from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, Optional

import typer
from rich import print

gui_app = typer.Typer(no_args_is_help=False, invoke_without_command=True)
_RELAUNCH_GUARD = "ACFV_SKIP_ENV_RELAUNCH"
_PREFERRED_PYTHON_ENV = "ACFV_GUI_PREFERRED_PYTHON"


@gui_app.callback()
def _entry(ctx: typer.Context):
    """Launch GUI when no subcommand is given."""
    if ctx.invoked_subcommand is None:
        _launch()


@gui_app.command("run")
def run():
    """Explicitly launch the GUI."""
    _launch()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _src_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _probe_current_python() -> Dict[str, object]:
    info: Dict[str, object] = {
        "python": sys.version.split()[0],
        "PyQt5": importlib.util.find_spec("PyQt5") is not None,
        "faster_whisper": importlib.util.find_spec("faster_whisper") is not None,
        "openai_whisper": importlib.util.find_spec("whisper") is not None,
        "torch": importlib.util.find_spec("torch") is not None,
        "cuda": False,
        "cuda_count": 0,
    }
    if info["torch"]:
        try:
            import torch

            info["torch_version"] = getattr(torch, "__version__", "")
            info["cuda"] = bool(torch.cuda.is_available())
            info["cuda_count"] = int(torch.cuda.device_count()) if info["cuda"] else 0
        except Exception as exc:  # noqa: BLE001
            info["torch_error"] = str(exc)
    return info


def _probe_python_env(python_path: Path) -> Optional[Dict[str, object]]:
    if not python_path.exists():
        return None
    script = (
        "import importlib.util, json, sys\n"
        "out={'python':sys.version.split()[0],"
        "'PyQt5': importlib.util.find_spec('PyQt5') is not None,"
        "'faster_whisper': importlib.util.find_spec('faster_whisper') is not None,"
        "'openai_whisper': importlib.util.find_spec('whisper') is not None,"
        "'torch': importlib.util.find_spec('torch') is not None,"
        "'cuda': False,"
        "'cuda_count': 0}\n"
        "try:\n"
        " import torch\n"
        " out['torch_version']=getattr(torch,'__version__','')\n"
        " out['cuda']=bool(torch.cuda.is_available())\n"
        " out['cuda_count']=int(torch.cuda.device_count()) if out['cuda'] else 0\n"
        "except Exception as exc:\n"
        " out['torch_error']=str(exc)\n"
        "print(json.dumps(out, ensure_ascii=False))\n"
    )
    env = os.environ.copy()
    env.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    try:
        proc = subprocess.run(
            [str(python_path), "-c", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=12,
            env=env,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    text = (proc.stdout or "").strip().splitlines()
    if not text:
        return None
    try:
        return json.loads(text[-1])
    except Exception:
        return None


def _derive_conda_root(current_python: Path) -> Optional[Path]:
    for parent in [current_python.parent, *current_python.parents]:
        if (parent / "envs").is_dir():
            return parent
    return None


def _candidate_python_paths(current_python: Path) -> Iterable[Path]:
    explicit = os.environ.get(_PREFERRED_PYTHON_ENV, "").strip()
    seen = set()
    if explicit:
        path = Path(explicit)
        seen.add(str(path).lower())
        yield path
    conda_root = _derive_conda_root(current_python)
    if conda_root is None:
        return
    envs_dir = conda_root / "envs"
    preferred_names = ["clip", "acfv", "subtitle", "sunomi"]
    for name in preferred_names:
        path = envs_dir / name / "python.exe"
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        yield path
    for env_dir in sorted(envs_dir.glob("*")):
        path = env_dir / "python.exe"
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        yield path


def _env_score(info: Dict[str, object]) -> int:
    score = 0
    if info.get("PyQt5"):
        score += 10
    if info.get("faster_whisper"):
        score += 20
    if info.get("cuda"):
        score += 40
    if info.get("openai_whisper"):
        score += 5
    return score


def _pick_better_python(current_python: Path, current_info: Dict[str, object]) -> Optional[Path]:
    current_score = _env_score(current_info)
    for candidate in _candidate_python_paths(current_python):
        if str(candidate).lower() == str(current_python).lower():
            continue
        info = _probe_python_env(candidate)
        if not info or not info.get("PyQt5"):
            continue
        if _env_score(info) > current_score:
            return candidate
    return None


def _maybe_relaunch_in_better_env() -> bool:
    if os.environ.get(_RELAUNCH_GUARD) == "1":
        return False
    current_python = Path(sys.executable).resolve()
    current_info = _probe_current_python()
    better_python = _pick_better_python(current_python, current_info)
    if better_python is None:
        return False

    env = os.environ.copy()
    env[_RELAUNCH_GUARD] = "1"
    env.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    src_root = str(_src_root())
    existing = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = src_root if not existing else f"{src_root}{os.pathsep}{existing}"

    print(f"[yellow]检测到当前 Python 环境不适合 GUI/转录，正在切换到:[/] {better_python}")
    subprocess.Popen(
        [str(better_python), "-m", "acfv.cli", "gui", "run"],
        cwd=str(_repo_root()),
        env=env,
    )
    return True


def _launch():
    if _maybe_relaunch_in_better_env():
        raise typer.Exit(code=0)
    try:
        from acfv.app.gui import launch_gui
    except Exception as e:  # noqa: BLE001
        print(f"[red]无法导入 GUI 启动器: {e}[/red]")
        raise typer.Exit(code=1)
    print("[bold]ACFV GUI[/] launching…")
    launch_gui()


__all__ = [
    "gui_app",
    "_candidate_python_paths",
    "_derive_conda_root",
    "_env_score",
    "_pick_better_python",
]
