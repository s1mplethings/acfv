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
_DISABLE_START_IN_TRAY = "ACFV_DISABLE_START_IN_TRAY"


@gui_app.callback()
def _entry(
    ctx: typer.Context,
    open_recording: str | None = typer.Option(None, "--open-recording"),
    open_review: bool = typer.Option(False, "--open-review"),
    event_plan: Path | None = typer.Option(None, "--event-plan", exists=True, dir_okay=False),
    output_root: Path | None = typer.Option(None, "--output-root", file_okay=False),
):
    """Launch GUI when no subcommand is given."""
    if ctx.invoked_subcommand is None:
        _launch(open_recording=open_recording, open_review=open_review,
                event_plan=event_plan, output_root=output_root)


@gui_app.command("run")
def run(
    open_recording: str | None = typer.Option(None, "--open-recording"),
    open_review: bool = typer.Option(False, "--open-review"),
    event_plan: Path | None = typer.Option(None, "--event-plan", exists=True, dir_okay=False),
    output_root: Path | None = typer.Option(None, "--output-root", file_okay=False),
):
    """Explicitly launch the GUI."""
    _launch(open_recording=open_recording, open_review=open_review,
            event_plan=event_plan, output_root=output_root)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _src_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _probe_current_python() -> Dict[str, object]:
    info: Dict[str, object] = {
        "python": sys.version.split()[0],
        "PyQt5": importlib.util.find_spec("PyQt5") is not None,
        "sqlmodel": importlib.util.find_spec("sqlmodel") is not None,
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
        "'sqlmodel': importlib.util.find_spec('sqlmodel') is not None,"
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


def _gui_ready(info: Dict[str, object]) -> bool:
    return bool(info.get("PyQt5") and info.get("sqlmodel"))


def _pick_better_python(current_python: Path, current_info: Dict[str, object]) -> Optional[Path]:
    current_score = _env_score(current_info)
    for candidate in _candidate_python_paths(current_python):
        if str(candidate).lower() == str(current_python).lower():
            continue
        info = _probe_python_env(candidate)
        if not info or not _gui_ready(info):
            continue
        if _env_score(info) > current_score:
            return candidate
    return None


def _maybe_relaunch_in_better_env(deep_link: dict[str, object] | None = None) -> bool:
    if os.environ.get(_RELAUNCH_GUARD) == "1":
        return False
    current_python = Path(sys.executable).resolve()
    current_info = _probe_current_python()
    better_python = _pick_better_python(current_python, current_info)
    if better_python is None:
        return False

    env = os.environ.copy()
    env[_RELAUNCH_GUARD] = "1"
    env[_DISABLE_START_IN_TRAY] = "1"
    env.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    src_root = str(_src_root())
    existing = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = src_root if not existing else f"{src_root}{os.pathsep}{existing}"

    print(f"[yellow]检测到当前 Python 环境不适合 GUI/转录，正在切换到:[/] {better_python}")
    args = [str(better_python), "-m", "acfv.cli", "gui", "run"]
    if deep_link:
        if deep_link.get("recording_id"):
            args.extend(["--open-recording", str(deep_link["recording_id"])])
        if deep_link.get("open_review"):
            args.append("--open-review")
        if deep_link.get("event_plan"):
            args.extend(["--event-plan", str(deep_link["event_plan"])])
        if deep_link.get("output_root"):
            args.extend(["--output-root", str(deep_link["output_root"])])
    subprocess.Popen(
        args,
        cwd=str(_repo_root()),
        env=env,
    )
    return True


def _launch(*, open_recording: str | None = None, open_review: bool = False,
            event_plan: Path | None = None, output_root: Path | None = None):
    os.environ.setdefault(_DISABLE_START_IN_TRAY, "1")
    deep_link = {
        "recording_id": open_recording,
        "open_review": open_review,
        "event_plan": str(event_plan.resolve()) if event_plan else None,
        "output_root": str(output_root.resolve()) if output_root else None,
    }
    if any(deep_link.values()):
        relaunch = _maybe_relaunch_in_better_env(deep_link)
    else:
        relaunch = _maybe_relaunch_in_better_env()
    if relaunch:
        raise typer.Exit(code=0)
    try:
        from acfv.app.gui import launch_gui
    except Exception as e:  # noqa: BLE001
        print(f"[red]无法导入 GUI 启动器: {e}[/red]")
        raise typer.Exit(code=1)
    print("[bold]ACFV GUI[/] launching…")
    if any(deep_link.values()):
        launch_gui(deep_link=deep_link)
    else:
        launch_gui()


__all__ = [
    "gui_app",
    "_candidate_python_paths",
    "_derive_conda_root",
    "_DISABLE_START_IN_TRAY",
    "_env_score",
    "_pick_better_python",
]
