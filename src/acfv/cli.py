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
