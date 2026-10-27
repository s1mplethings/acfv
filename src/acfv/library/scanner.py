from __future__ import annotations

import threading
import time
import subprocess
from pathlib import Path
from typing import Callable, Iterable, Optional

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

VIDEO_EXTENSIONS = frozenset({".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts"})


def canonical_path(path: Path | str) -> str:
    return str(Path(path).expanduser().resolve())


def is_supported_video(path: Path | str) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def probe_duration_ms(path: Path | str) -> Optional[int]:
    """Return container duration without making media probing an import requirement."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(Path(path).expanduser().resolve()),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if result.returncode != 0:
            return None
        seconds = float(result.stdout.strip())
        return max(0, int(round(seconds * 1000)))
    except (FileNotFoundError, OSError, ValueError, subprocess.SubprocessError):
        return None


def iter_video_files(folder: Path | str) -> Iterable[Path]:
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Library folder does not exist: {root}")
    for path in sorted(root.rglob("*")):
        if path.is_file() and is_supported_video(path):
            yield path


def wait_until_stable(path: Path | str, interval: float = 1.0, checks: int = 2) -> bool:
    candidate = Path(path)
    previous = None
    stable_count = 0
    while stable_count < max(1, checks):
        try:
            stat = candidate.stat()
        except OSError:
            return False
        current = (stat.st_size, stat.st_mtime_ns)
        stable_count = stable_count + 1 if current == previous else 0
        previous = current
        if stable_count < checks:
            time.sleep(max(0.0, interval))
    return True


class _VideoCreatedHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[Path], None], interval: float, checks: int) -> None:
        self.callback = callback
        self.interval = interval
        self.checks = checks

    def on_created(self, event) -> None:
        if event.is_directory or not is_supported_video(event.src_path):
            return
        path = Path(event.src_path)
        threading.Thread(target=self._register, args=(path,), daemon=True).start()

    def _register(self, path: Path) -> None:
        if wait_until_stable(path, interval=self.interval, checks=self.checks):
            self.callback(path)


class LibraryFolderWatcher:
    def __init__(self) -> None:
        self._observer: Optional[Observer] = None

    def start(self, folder: Path | str, callback: Callable[[Path], None], *, interval: float = 2.0, checks: int = 2) -> None:
        self.stop()
        observer = Observer()
        observer.schedule(_VideoCreatedHandler(callback, interval, checks), canonical_path(folder), recursive=True)
        observer.start()
        self._observer = observer

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
