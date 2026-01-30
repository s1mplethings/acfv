import json
import logging
import sys
from pathlib import Path
from typing import Optional


class JsonLineFormatter(logging.Formatter):
    """极简 JSON 行格式化，保证可被采集/追踪。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # 附加可选字段
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(settings, *, level: str = "INFO", structured_path: Optional[Path] = None):
    """
    初始化日志：
    - 人类可读：stdout
    - 采集友好：JSONL 文件
    """
    Path(settings.workdir).mkdir(parents=True, exist_ok=True)
    text_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(text_formatter)

    structured_file = structured_path or (Path(settings.workdir) / "acfv.log.jsonl")
    json_handler = logging.FileHandler(structured_file, encoding="utf-8")
    json_handler.setFormatter(JsonLineFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.addHandler(console_handler)
    root.addHandler(json_handler)
