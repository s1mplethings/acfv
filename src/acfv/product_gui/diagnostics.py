"""Session logging and user-facing uncaught-exception handling."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
import sys
import traceback
import uuid

from acfv.runtime.storage import logs_path


def configure_gui_diagnostics() -> tuple[str, Path]:
    session_id = uuid.uuid4().hex[:12]
    path = logs_path("gui", f"session-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{session_id}.log")
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s session=%(session_id)s %(message)s"))

    class SessionFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            record.session_id = session_id
            return True

    handler.addFilter(SessionFilter())
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(min(root.level or logging.INFO, logging.INFO))
    logging.getLogger(__name__).info("GUI session started")
    return session_id, path


def install_exception_dialog(log_path: Path) -> None:
    previous = sys.excepthook

    def handle(exc_type, value, tb) -> None:
        details = "".join(traceback.format_exception(exc_type, value, tb))
        logging.getLogger(__name__).critical("Uncaught GUI exception\n%s", details)
        try:
            from PyQt5.QtWidgets import QMessageBox

            box = QMessageBox()
            box.setIcon(QMessageBox.Critical)
            box.setWindowTitle("ACFV")
            box.setText("Something went wrong")
            box.setInformativeText("错误已写入本次 GUI 日志。可以展开详情后重试或安全关闭应用。")
            box.setDetailedText(f"Log: {log_path}\n\n{details}")
            box.exec_()
        except Exception:
            previous(exc_type, value, tb)

    sys.excepthook = handle

