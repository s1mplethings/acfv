"""Unified HuggingFace token loader.

Usage:
    from acfv.runtime.token_loader import get_hf_token

Discovery order (first non-empty wins):
 1. Environment variable HUGGINGFACE_TOKEN
 2. var/secrets/config.json (key: huggingface_token)
 3. huggingface_token.txt (repository root or var/secrets/)
 4. legacy file ./huggingface_token.txt

If no token is found, returns "" and logs a single warning (deduplicated).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from functools import lru_cache

from .storage import secrets_path, storage_root
try:
    from acfv.config.config import ConfigManager  # lazy import to avoid cycles
except Exception:  # noqa: BLE001
    ConfigManager = None  # type: ignore

_warned = False


def _read_text_file(path: Path) -> str:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except OSError as e:  # noqa: BLE001
        logging.debug("读取 token 文件失败 %s: %s", path, e)
    return ""


def _read_config_json(path: Path) -> str:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            token = data.get("huggingface_token") or data.get("HUGGINGFACE_TOKEN") or ""
            return str(token).strip()
    except Exception as e:  # noqa: BLE001
        logging.debug("解析 token json 失败 %s: %s", path, e)
    return ""


@lru_cache(maxsize=1)
def get_hf_token() -> str:
    # 1) ConfigManager (用户界面设置优先)
    if ConfigManager is not None:
        try:
            cfg = ConfigManager()
            t_cfg = str(cfg.get("HUGGINGFACE_TOKEN", "")).strip()
            if t_cfg:
                os.environ.setdefault("HUGGINGFACE_TOKEN", t_cfg)
                return t_cfg
        except Exception:
            pass

    # 2) 环境变量
    token = os.environ.get("HUGGINGFACE_TOKEN", "").strip()
    if token:
        return token

    # secrets/config.json
    token = _read_config_json(secrets_path("config.json"))
    if token:
        return token

    # repo root huggingface_token.txt
    repo_root = storage_root().parents[0]
    token = _read_text_file(repo_root / "huggingface_token.txt")
    if token:
        return token

    # secrets folder token
    token = _read_text_file(secrets_path("huggingface_token.txt"))
    if token:
        return token

    global _warned
    if not _warned:
        logging.warning("⚠️ HuggingFace token 未配置，说话人分离或模型下载功能可能不可用")
        _warned = True
    return ""


__all__ = ["get_hf_token"]

def set_hf_token(token: str) -> None:
    """Programmatically update the HuggingFace token (persist if ConfigManager available)."""
    os.environ["HUGGINGFACE_TOKEN"] = token.strip()
    if ConfigManager is not None:
        try:
            cfg = ConfigManager()
            cfg.set("HUGGINGFACE_TOKEN", token.strip())
        except Exception:
            pass

__all__.append("set_hf_token")