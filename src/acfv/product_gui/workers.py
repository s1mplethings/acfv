"""One executor for all GUI background work with stale-result protection."""

from __future__ import annotations

import itertools
import logging
import threading
import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from PyQt5.QtCore import QObject, pyqtSignal


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RequestToken:
    channel: str
    generation: int


class _Signals(QObject):
    completed = pyqtSignal(object, object)
    failed = pyqtSignal(object, str, str)
    progress = pyqtSignal(object, object)


class GuiExecutor(QObject):
    """Thread-pool adapter shared by every page.

    A monotonically increasing token is issued per channel.  Completion is
    delivered only when the token is still current, so a slow Creator A or
    query Q1 cannot overwrite Creator B or query Q2.
    """

    result_ready = pyqtSignal(object, object)
    task_failed = pyqtSignal(object, str, str)
    task_progress = pyqtSignal(object, object)

    def __init__(self, max_workers: int = 4, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="acfv-gui")
        self._sequence = itertools.count(1)
        self._current: dict[str, RequestToken] = {}
        self._futures: dict[RequestToken, Future[Any]] = {}
        self._closed = threading.Event()
        self._signals = _Signals()
        self._signals.completed.connect(self._deliver_result)
        self._signals.failed.connect(self._deliver_failure)
        self._signals.progress.connect(self._deliver_progress)

    def submit(self, channel: str, operation: Callable[..., Any], *args: Any, **kwargs: Any) -> RequestToken:
        if self._closed.is_set():
            raise RuntimeError("GUI executor is closed")
        token = RequestToken(channel, next(self._sequence))
        self._current[channel] = token

        def report(value: Any) -> None:
            if not self._closed.is_set():
                self._safe_emit(self._signals.progress, token, value)

        def run() -> None:
            try:
                if kwargs.pop("_with_progress", False):
                    value = operation(*args, progress=report, **kwargs)
                else:
                    value = operation(*args, **kwargs)
                if not self._closed.is_set():
                    self._safe_emit(self._signals.completed, token, value)
            except Exception as exc:  # noqa: BLE001 - GUI boundary
                if not self._closed.is_set():
                    LOGGER.exception("GUI task failed channel=%s generation=%s", token.channel, token.generation)
                    self._safe_emit(self._signals.failed, token, str(exc), traceback.format_exc())
            finally:
                self._futures.pop(token, None)

        self._futures[token] = self._pool.submit(run)
        return token

    def invalidate(self, channel: str) -> RequestToken:
        token = RequestToken(channel, next(self._sequence))
        self._current[channel] = token
        return token

    def is_current(self, token: RequestToken) -> bool:
        return self._current.get(token.channel) == token

    def _deliver_result(self, token: RequestToken, value: Any) -> None:
        if self.is_current(token):
            self.result_ready.emit(token, value)

    def _deliver_failure(self, token: RequestToken, message: str, details: str) -> None:
        if self.is_current(token):
            self.task_failed.emit(token, message, details)

    def _deliver_progress(self, token: RequestToken, value: Any) -> None:
        if self.is_current(token):
            self.task_progress.emit(token, value)

    def shutdown(self, wait: bool = False) -> None:
        self._closed.set()
        for channel in tuple(self._current):
            self.invalidate(channel)
        self._pool.shutdown(wait=wait, cancel_futures=True)

    @staticmethod
    def _safe_emit(signal: Any, *args: Any) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:
            # Qt may destroy the signal owner while an in-flight operation is
            # completing during application shutdown. The result is obsolete.
            return

