#!/usr/bin/env bash
# acfv_packaging.sh
# 重构为“安装后可直接使用”的结构；不创建分支、不提交，不推送。

set -Eeuo pipefail

# 0) 预检
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  HAS_GIT=1
  ROOT="$(git rev-parse --show-toplevel)"
else
  HAS_GIT=0
  ROOT="$(pwd)"
fi
cd "$ROOT"

mkdir -p src/acfv/assets

# 便捷移动：若在 git 里且文件受管，用 git mv；否则用 mv
track_mv() {
  local src="$1" dst="$2"
  [ -e "$src" ] || return 0
  mkdir -p "$(dirname "$dst")"
  if [ "$HAS_GIT" = "1" ] && git ls-files --error-unmatch "$src" >/dev/null 2>&1; then
    git mv -f "$src" "$dst"
  else
    mv -f "$src" "$dst"
  fi
}

# 1) 迁移目录/文件进包
track_mv config                    src/acfv/config
track_mv data                      src/acfv/data
track_mv processing                src/acfv/processing

track_mv launcher.py               src/acfv/launcher.py
track_mv clip_video.py             src/acfv/clip_video.py
track_mv clip_video_clean.py       src/acfv/clip_video_clean.py
track_mv main_logging.py           src/acfv/main_logging.py
track_mv error_handler.py          src/acfv/error_handler.py
track_mv safe_callbacks.py         src/acfv/safe_callbacks.py
track_mv silent_exit.py            src/acfv/silent_exit.py
track_mv subprocess_utils.py       src/acfv/subprocess_utils.py
track_mv utils.py                  src/acfv/utils.py
track_mv warning_manager.py        src/acfv/warning_manager.py
track_mv background_runtime.py     src/acfv/background_runtime.py
track_mv rag_module.py             src/acfv/rag_module.py
track_mv rag_vector_database.py    src/acfv/rag_vector_database.py

track_mv TwitchDownloaderCLI.exe   src/acfv/assets/TwitchDownloaderCLI.exe
track_mv best.pt                   src/acfv/assets/best.pt

# 2) 包标记（不自动 git add/commit）
for d in src/acfv src/acfv/processing src/acfv/config src/acfv/data; do
  if [ -d "$d" ] && [ ! -e "$d/__init__.py" ]; then
    printf '%s\n' '"""Package marker."""' > "$d/__init__.py"
  fi
done

# 3) pyproject.toml（覆盖生成；不提交）
cat > pyproject.toml <<'TOML'
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "acfv"
version = "0.1.0"
description = "ACFV – tools for VTuber clip workflows"
readme = "README.md"
requires-python = ">=3.9"
dependencies = []

[tool.setuptools]
include-package-data = true

[tool.setuptools.packages.find]
where = ["src"]
include = ["acfv*"]

[tool.setuptools.package-data]
acfv = [
  "config/**/*",
  "processing/**/*",
  "data/**/*",
  "assets/*",
  "*.yaml",
  "*.yml",
]

[project.scripts]
acfv = "acfv.cli:main"
acfv-gui = "acfv.cli:main_gui"
TOML

# 4) 包入口与工具
cat > src/acfv/__init__.py <<'PY'
from importlib import metadata
try:
    __version__ = metadata.version("acfv")
except metadata.PackageNotFoundError:
    __version__ = "0.0.0"
PY

cat > src/acfv/__main__.py <<'PY'
from .cli import main
if __name__ == "__main__":
    raise SystemExit(main())
PY

cat > src/acfv/paths.py <<'PY'
from importlib.resources import files
from pathlib import Path

PKG_ROOT = files("acfv")

def pkg_path(*parts: str) -> Path:
    return Path(PKG_ROOT.joinpath(*parts))

def assets_path(*parts: str) -> Path:
    return pkg_path("assets", *parts)

def config_path(*parts: str) -> Path:
    return pkg_path("config", *parts)

def data_path(*parts: str) -> Path:
    return pkg_path("data", *parts)

def processing_path(*parts: str) -> Path:
    return pkg_path("processing", *parts)
PY

cat > src/acfv/cli.py <<'PY'
import sys
import argparse
from pathlib import Path
from .paths import assets_path, config_path

def _try_call(module_name: str, func_candidates=("main", "run", "app", "start")):
    mod = __import__(f"acfv.{module_name}", fromlist=["*"])
    for fn in func_candidates:
        if hasattr(mod, fn):
            return getattr(mod, fn)()
    raise AttributeError(f"Module 'acfv.{module_name}' has no {func_candidates} entry.")

def _inject_compat_paths():
    pkg_root = Path(__file__).resolve().parent
    rt_candidates = [
        pkg_root,
        pkg_root / "assets",
        pkg_root / "config",
        pkg_root.parent.parent,   # repo root in -e dev mode
    ]
    for p in rt_candidates:
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="acfv", add_help=True)
    parser.add_argument("--gui", action="store_true", help="Launch GUI (acfv.launcher)")
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    subparsers = parser.add_subparsers(dest="sub", metavar="subcommand")
    subparsers.add_parser("clip", help="Run clip_video pipeline")
    subparsers.add_parser("clip-clean", help="Run clip_video_clean pipeline")
    ns, rest = parser.parse_known_args(argv)

    if ns.version:
        from . import __version__
        print(__version__)
        return 0

    _inject_compat_paths()

    import os
    os.environ.setdefault("ACFV_ASSETS_DIR", str(assets_path()))
    os.environ.setdefault("ACFV_CONFIG_DIR", str(config_path()))

    if ns.gui:
        return _try_call("launcher")

    if ns.sub == "clip":
        sys.argv = ["clip_video"] + rest
        return _try_call("clip_video")

    if ns.sub == "clip-clean":
        sys.argv = ["clip_video_clean"] + rest
        return _try_call("clip_video_clean")

    return _try_call("launcher")

def main_gui():
    return _try_call("launcher")
PY

# 5) .gitignore（可选）
if [ ! -e .gitignore ]; then
  cat > .gitignore <<'IGN'
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.venv/
.env
.DS_Store
IGN
fi

# 6) 结束提示（仅打印）
printf '%s\n' "DONE. Next:
  pip uninstall -y acfv 2>/dev/null || true
  pip install -e .
  acfv --help
  acfv --gui
  acfv clip --help"
