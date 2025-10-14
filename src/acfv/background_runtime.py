#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Background runtime manager for non-GUI operations.

Responsibilities:
- Environment / version / dependency self-checks
- Directory & config initialization
- Video mapping initialization
- Crash & exception safety handlers (non-GUI)
- Background task scheduling helpers
- Subprocess safety wrapper
- Process / thread cleanup
- JSONL -> JSON conversion utility (for data consolidation before GUI loads)

This module is intentionally GUI-agnostic (no PyQt imports).
"""

from __future__ import annotations
import os
import sys
import json
import time
import atexit
import logging
import traceback
import threading
from typing import Callable, List, Optional, Dict, Any, Iterable

# ---------------------------------------------------------------------------
# Constants & Globals
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_LOG_INITIALIZED = False
_CLEANUP_RAN = False
_BACKGROUND_THREADS: List[threading.Thread] = []
_TASK_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Public API (import-friendly)
# ---------------------------------------------------------------------------

__all__ = [
    "BackgroundRuntime",
    "convert_jsonl_to_json",
    "bulk_convert_jsonl",
    "safe_subprocess_run",
    "register_background_task",
    "shutdown_background_tasks",
]

# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------

def _bootstrap_logging(level: str = "INFO", log_dir: Optional[str] = None):
    global _LOG_INITIALIZED
    if _LOG_INITIALIZED:
        return
    log_dir = log_dir or os.path.join(BASE_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "background_runtime.log")

    root = logging.getLogger()
    if not root.handlers:
        handler = logging.FileHandler(log_file, encoding="utf-8")
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(threadName)s | %(name)s: %(message)s"
        )
        handler.setFormatter(fmt)
        root.addHandler(handler)
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(fmt)
        root.addHandler(console)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    _LOG_INITIALIZED = True
    logging.debug("Logging initialized")


# ---------------------------------------------------------------------------
# JSONL Utilities
# ---------------------------------------------------------------------------

def convert_jsonl_to_json(jsonl_path: str, json_path: Optional[str] = None) -> Optional[str]:
    """
    Convert a JSONL file to a JSON array file.
    Returns the output JSON path or None if conversion failed.
    Skips if input file does not exist or is empty.
    """
    try:
        if not os.path.exists(jsonl_path):
            logging.debug(f"JSONL source not found: {jsonl_path}")
            return None
        if os.path.isdir(jsonl_path):
            logging.warning(f"Path is a directory, skipping: {jsonl_path}")
            return None

        if json_path is None:
            base, _ = os.path.splitext(jsonl_path)
            json_path = base + ".json"

        records = []
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    logging.warning(f"Invalid JSONL line {line_no} in {jsonl_path}: {e}")
        with open(json_path, "w", encoding="utf-8") as out:
            json.dump(records, out, ensure_ascii=False, indent=2)
        logging.info(f"Converted JSONL -> JSON: {jsonl_path} -> {json_path} ({len(records)} records)")
        return json_path
    except Exception as e:
        logging.error(f"Failed converting JSONL: {jsonl_path}: {e}")
        return None


def bulk_convert_jsonl(
    directory: str,
    suffix: str = ".jsonl",
    recursive: bool = False,
    skip_existing: bool = True
) -> Dict[str, Optional[str]]:
    """
    Convert all JSONL files inside a directory.
    Returns mapping of source jsonl -> converted json (or None if failed).
    """
    results: Dict[str, Optional[str]] = {}
    if not os.path.isdir(directory):
        logging.debug(f"bulk_convert_jsonl: directory not found: {directory}")
        return results

    def _iter_files():
        if recursive:
            for root, _, files in os.walk(directory):
                for f in files:
                    if f.lower().endswith(suffix):
                        yield os.path.join(root, f)
        else:
            for f in os.listdir(directory):
                if f.lower().endswith(suffix):
                    yield os.path.join(directory, f)

    for jsonl_path in _iter_files():
        base, _ = os.path.splitext(jsonl_path)
        json_path = base + ".json"
        if skip_existing and os.path.exists(json_path):
            logging.debug(f"Skipping existing JSON: {json_path}")
            results[jsonl_path] = json_path
            continue
        results[jsonl_path] = convert_jsonl_to_json(jsonl_path, json_path)
    return results


# ---------------------------------------------------------------------------
# Subprocess Utility
# ---------------------------------------------------------------------------

def safe_subprocess_run(*args, **kwargs):
    """
    Wrapper around subprocess.run adding default UTF-8 encoding when text=True.
    """
    import subprocess
    if kwargs.get("text"):
        kwargs.setdefault("encoding", "utf-8")
        kwargs.setdefault("errors", "ignore")
    return subprocess.run(*args, **kwargs)


# ---------------------------------------------------------------------------
# Background Task Management
# ---------------------------------------------------------------------------

def register_background_task(target: Callable, name: Optional[str] = None, daemon: bool = True, start: bool = True, args: Iterable = (), kwargs: Optional[Dict[str, Any]] = None) -> threading.Thread:
    """
    Register and (optionally) start a background thread.
    """
    kwargs = kwargs or {}
    thread = threading.Thread(target=target, name=name or f"bg-{int(time.time()*1000)}", args=args, kwargs=kwargs, daemon=daemon)
    with _TASK_LOCK:
        _BACKGROUND_THREADS.append(thread)
    if start:
        thread.start()
    return thread


def shutdown_background_tasks(timeout: float = 2.0):
    """
    Best-effort wait for background threads to finish.
    Only joins non-daemon threads (daemons exit automatically).
    """
    with _TASK_LOCK:
        threads = list(_BACKGROUND_THREADS)
    for t in threads:
        if t.is_alive() and not t.daemon:
            try:
                t.join(timeout=timeout)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Cleanup & Process Termination
# ---------------------------------------------------------------------------

def _force_terminate_child_processes():
    try:
        import psutil
    except ImportError:
        logging.debug("psutil not available for child process cleanup")
        return
    try:
        current = psutil.Process(os.getpid())
        children = current.children(recursive=True)
        if not children:
            logging.debug("No child processes to terminate")
            return
        for proc in children:
            try:
                proc.kill()
            except Exception:
                pass
        logging.info(f"Terminated {len(children)} child processes")
    except Exception as e:
        logging.debug(f"Child process termination skipped: {e}")


def _global_cleanup():
    global _CLEANUP_RAN
    if _CLEANUP_RAN:
        return
    _CLEANUP_RAN = True
    logging.debug("Running background runtime cleanup...")
    try:
        shutdown_background_tasks()
    except Exception:
        pass
    try:
        _force_terminate_child_processes()
    except Exception:
        pass


atexit.register(_global_cleanup)


# ---------------------------------------------------------------------------
# Crash / Fault Handling
# ---------------------------------------------------------------------------

def _setup_fault_handlers(log_dir: str):
    try:
        import faulthandler
        crash_file = os.path.join(log_dir, "crash_dump.log")
        f = open(crash_file, "a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=f, all_threads=True)
    except Exception as e:
        logging.debug(f"faulthandler setup failed: {e}")


def _set_windows_error_mode():
    try:
        if sys.platform.startswith("win"):
            import ctypes
            SEM_FAILCRITICALERRORS = 0x0001
            SEM_NOGPFAULTERRORBOX = 0x0002
            SEM_NOOPENFILEERRORBOX = 0x8000
            ctypes.windll.kernel32.SetErrorMode(
                SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX
            )
    except Exception as e:
        logging.debug(f"SetErrorMode failed: {e}")


# ---------------------------------------------------------------------------
# Core Runtime Class
# ---------------------------------------------------------------------------

class BackgroundRuntime:
    """
    Encapsulates all non-GUI initialization & background management.
    """

    def __init__(self, log_level: str = "INFO"):
        _bootstrap_logging(log_level)
        self.log_level = log_level
        logging.debug("BackgroundRuntime created")

    # ----- Public Lifecycle -------------------------------------------------

    def initialize(self):
        """
        Perform startup procedures: version/dependency checks, directories, configs, safety handlers.
        Safe to call multiple times (idempotent-ish).
        """
        logging.info("Initializing background runtime...")
        self._check_python_version()
        self._ensure_directories()
        self._create_default_config()
        self._init_video_mapping()
        self._light_dependency_check()
        _set_windows_error_mode()
        _setup_fault_handlers(os.path.join(BASE_DIR, "data", "logs"))
        self._install_thread_excepthook()
        self._install_unraisable_hook()
        logging.info("Background runtime initialized")

    def prepare_before_gui(self, jsonl_scan_dir: Optional[str] = None, recursive: bool = False):
        """
        Hook to be called right before launching the GUI.
        Handles JSONL -> JSON consolidation or other pre-GUI data transforms.
        """
        logging.info("Preparing data before GUI startup...")
        if jsonl_scan_dir:
            bulk_convert_jsonl(jsonl_scan_dir, recursive=recursive)
        logging.info("Pre-GUI preparation done")

    def shutdown(self):
        """
        Explicit shutdown (also called automatically at exit).
        """
        logging.info("Shutting down background runtime...")
        _global_cleanup()

    # ----- Checks & Initialization ------------------------------------------

    @staticmethod
    def _check_python_version():
        if sys.version_info < (3, 8):
            raise RuntimeError(f"Python 3.8+ required, got {sys.version}")
        logging.debug(f"Python version OK: {sys.version.split()[0]}")

    @staticmethod
    def _light_dependency_check():
        # Minimal critical dependency checks; others can lazy-load
        try:
            __import__("json")
        except ImportError as e:
            raise RuntimeError(f"Critical dependency missing: {e}")
        logging.debug("Core dependency check passed")

    @staticmethod
    def _ensure_directories():
        paths = [
            os.path.join(BASE_DIR, "logs"),
            os.path.join(BASE_DIR, "processing"),
            os.path.join(BASE_DIR, "data"),
            os.path.join(BASE_DIR, "data", "logs"),
            os.path.join(BASE_DIR, "config"),
        ]
        for p in paths:
            try:
                os.makedirs(p, exist_ok=True)
            except Exception as e:
                logging.error(f"Failed creating directory {p}: {e}")

    @staticmethod
    def _create_default_config():
        cfg_dir = os.path.join(BASE_DIR, "config")
        os.makedirs(cfg_dir, exist_ok=True)
        cfg_path = os.path.join(cfg_dir, "config.txt")
        if os.path.exists(cfg_path):
            logging.debug("Config already exists, skipping creation")
            return
        default_cfg = {
            "CLIPS_BASE_DIR": "clips",
            "MAX_CLIP_COUNT": 10,
            "WHISPER_MODEL": "base",
            "ENABLE_VIDEO_EMOTION": False,
            "MAX_WORKERS": 2,
        }
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(default_cfg, f, ensure_ascii=False, indent=2)
            logging.debug(f"Default config created: {cfg_path}")
        except Exception as e:
            logging.error(f"Failed writing config: {e}")

    @staticmethod
    def _init_video_mapping():
        proc_dir = os.path.join(BASE_DIR, "processing")
        data_dir = os.path.join(BASE_DIR, "data")
        os.makedirs(proc_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)
        mapping_proc = os.path.join(proc_dir, "video_mappings.json")
        mapping_data = os.path.join(data_dir, "video_mappings.json")

        target = mapping_data  # choose canonical
        if not os.path.exists(target):
            try:
                with open(target, "w", encoding="utf-8") as f:
                    json.dump({}, f)
                logging.debug(f"Video mapping initialized: {target}")
            except Exception as e:
                logging.error(f"Failed initializing video mapping: {e}")

        # Symlink / copy to processing for legacy expectations
        try:
            if not os.path.exists(mapping_proc):
                with open(target, "r", encoding="utf-8") as src, open(mapping_proc, "w", encoding="utf-8") as dst:
                    dst.write(src.read())
        except Exception:
            pass

    # ----- Exception Handling ----------------------------------------------

    @staticmethod
    def _install_thread_excepthook():
        def _thread_excepthook(args):
            logging.error(
                "[thread] Uncaught exception",
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
        if hasattr(threading, "excepthook"):
            try:
                threading.excepthook = _thread_excepthook  # type: ignore
                logging.debug("threading.excepthook installed")
            except Exception:
                pass

    @staticmethod
    def _install_unraisable_hook():
        def _unraisable(unraisable):
            exc = getattr(unraisable, "exc", None)
            tb = exc.__traceback__ if exc else None
            logging.error(
                "[unraisable] exception",
                exc_info=(type(exc), exc, tb),
            )
        if hasattr(sys, "unraisablehook"):
            try:
                sys.unraisablehook = _unraisable  # type: ignore
                logging.debug("sys.unraisablehook installed")
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Convenience Factory
# ---------------------------------------------------------------------------

def create_background_runtime(log_level: str = "INFO") -> BackgroundRuntime:
    rt = BackgroundRuntime(log_level=log_level)
    rt.initialize()
    return rt


# ---------------------------------------------------------------------------
# Optional: Simple self-test when run standalone
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Minimal standalone test (no GUI)
    runtime = create_background_runtime(log_level=os.environ.get("LOG_LEVEL", "INFO"))
    # Demonstrate JSONL conversion (creates sample if absent)
    sample_jsonl = os.path.join(BASE_DIR, "data", "sample.jsonl")
    if not os.path.exists(sample_jsonl):
        with open(sample_jsonl, "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": 1, "text": "hello"}) + "\n")
            f.write(json.dumps({"id": 2, "text": "world"}) + "\n")
    convert_jsonl_to_json(sample_jsonl)
    runtime.prepare_before_gui(jsonl_scan_dir=os.path.join(BASE_DIR, "data"))
    print("Background runtime self-test complete.")
    runtime.shutdown()