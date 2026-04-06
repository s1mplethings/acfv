# main_logging.py

import logging
import sys
import os
import json
from datetime import datetime

from acfv.runtime.storage import logs_path

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

log_file = logs_path("processing.log")
jsonl_file = logs_path(f"processing_{datetime.now().strftime('%Y%m%d')}.log.jsonl")

# 配置日志：stdout 镜像 + 文件
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)

file_handler = logging.FileHandler(str(log_file), encoding='utf-8', mode='a')
file_handler.setLevel(logging.DEBUG)

class _JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)

json_handler = logging.FileHandler(str(jsonl_file), encoding="utf-8", mode="a")
json_handler.setLevel(logging.DEBUG)
json_handler.setFormatter(_JsonLineFormatter())

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[file_handler, json_handler, console_handler],
    force=True,  # 覆盖已有 handlers，确保 GUI 启动时也能打印到控制台
)

ECHO_STDOUT = os.environ.get("ACFV_ECHO_STDOUT", "1") not in ("0", "false", "False")
ECHO_DEBUG = os.environ.get("ACFV_ECHO_DEBUG", "0") not in ("0", "false", "False")

def _has_stdout_handler() -> bool:
    try:
        root = logging.getLogger()
        for handler in root.handlers:
            if isinstance(handler, logging.StreamHandler) and getattr(handler, "stream", None) is sys.stdout:
                return True
    except Exception:
        return False
    return False


def _render_message(message, args) -> str:
    if not args:
        return str(message)
    try:
        return str(message) % args
    except Exception:
        return " ".join([str(message), *[str(arg) for arg in args]])


def log_debug(message, *args, **kwargs):
    logging.debug(message, *args, **kwargs)
    if ECHO_STDOUT and ECHO_DEBUG and not _has_stdout_handler():
        print(_render_message(message, args), flush=True)


def log_info(message, *args, **kwargs):
    logging.info(message, *args, **kwargs)
    if ECHO_STDOUT and not _has_stdout_handler():
        print(_render_message(message, args), flush=True)


def log_error(message, *args, **kwargs):
    logging.error(message, *args, **kwargs)
    if ECHO_STDOUT and not _has_stdout_handler():
        print(_render_message(message, args), file=sys.stderr, flush=True)


def log_warning(message, *args, **kwargs):
    logging.warning(message, *args, **kwargs)
    if ECHO_STDOUT and not _has_stdout_handler():
        print(_render_message(message, args), flush=True)

# 添加启动日志
log_info("=" * 60)
log_info("日志系统启动")
log_info("当前时间: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
log_info("=" * 60)
