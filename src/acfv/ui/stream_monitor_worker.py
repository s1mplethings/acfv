"""Background thread wrapper that runs the Stream Monitor service inside the GUI."""

from __future__ import annotations

import asyncio
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from acfv.runtime.stream_monitor import MonitorEvent, StreamMonitorService, load_stream_monitor_config
from acfv.runtime.storage import logs_path


class StreamMonitorWorker(QThread):
    event_emitted = pyqtSignal(object)
    status_changed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, config_path: Path | None = None, log_path: Path | None = None):
        super().__init__()
        self.config_path = config_path
        self.log_path = log_path or logs_path("stream_monitor.log")
        self._loop: asyncio.AbstractEventLoop | None = None
        self._service: StreamMonitorService | None = None

    def run(self) -> None:
        try:
            config, cfg_path, _ = load_stream_monitor_config(self.config_path)
            self.config_path = cfg_path
        except Exception as exc:
            self.error_occurred.emit(f"配置加载失败: {exc}")
            return

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        def event_hook(evt: MonitorEvent) -> None:
            self.event_emitted.emit(evt)

        try:
            self._service = StreamMonitorService(
                config=config,
                event_hook=event_hook,
                log_path=self.log_path,
            )
            self.status_changed.emit("running")
            self._loop.run_until_complete(self._service.run())
        except Exception as exc:
            self.error_occurred.emit(f"监控器异常: {exc}")
        finally:
            self.status_changed.emit("stopped")
            if self._loop is not None:
                self._loop.stop()
                self._loop.close()
                self._loop = None
            self._service = None

    def request_stop(self) -> None:
        if self._loop and self._service:
            asyncio.run_coroutine_threadsafe(self._service.stop(), self._loop)
