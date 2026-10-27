#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Configuration helper used by processing modules.

Responsible for supplying the HuggingFace token from a safe location (env vars
preferred, file fallback).  Previous versions only read ``config.json`` next to
this module which produced warnings when the file was absent.  The helper now
honours environment variables and the shared ``secrets/config.json`` copy so
users can keep credentials outside the source tree.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Iterable, Optional

from acfv.runtime.storage import secrets_path
try:
    from acfv.warning_manager import warn_once  # reuse global once-set
except Exception:
    def warn_once(key: str, message: str):  # fallback
        logging.warning(message)


_ENV_TOKEN_KEYS: tuple[str, ...] = (
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HF_TOKEN",
    "huggingface_token",
    "huggingfacetoken",
)


def _search_token_in_env() -> Optional[str]:
    for key in _ENV_TOKEN_KEYS:
        value = os.environ.get(key)
        if value:
            logging.info("✅ HuggingFace token 已从环境变量 %s 读取", key)
            return value.strip()
    return None


def _candidate_paths(target: Path) -> Iterable[Path]:
    module_dir = Path(__file__).resolve().parent
    try:
        project_root = module_dir.parents[3]
    except IndexError:
        project_root = module_dir.parents[1]
    cwd = Path.cwd()
    yield target
    yield module_dir / "config.json"
    yield project_root / "secrets" / "config.json"
    if project_root != cwd:
        yield cwd / "secrets" / "config.json"


def load_huggingface_token() -> Optional[str]:
    """
    从配置文件或环境变量里读取 HuggingFace token.

    Returns:
        str | None: token 字符串，若读取失败返回 None。
    """
    token = _search_token_in_env()
    if token:
        return token

    target_path = secrets_path("config.json")
    config_path = next((path for path in _candidate_paths(target_path) if path.is_file()), None)
    if not config_path:
        warn_once(
            "hf_config_missing",
            "⚠️ 未找到 config.json，且环境变量未提供 HuggingFace token。复制 secrets/config.json.example 为 secrets/config.json 并填写 huggingface_token。",
        )
        return None
    if config_path != target_path:
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(config_path, target_path)
            logging.info("ℹ️ 已将 HuggingFace 配置迁移到 %s", target_path)
        except OSError as exc:
            logging.debug("迁移 HuggingFace 配置失败 (%s): %s", config_path, exc)
        config_path = target_path

    try:
        with config_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        logging.error("配置文件格式错误 (%s): %s", config_path, exc)
        return None
    except OSError as exc:
        logging.error("读取配置文件失败 (%s): %s", config_path, exc)
        return None

    token = (data.get("huggingface_token") or "").strip()
    if not token or token == "your_huggingface_token_here":
        warn_once(
            "hf_token_invalid",
            f"⚠️ HuggingFace token 未正确配置，请检查 {config_path}",
        )
        return None

    logging.info("✅ HuggingFace token 已从 %s 读取", config_path)
    return token


def setup_huggingface_environment() -> bool:
    """
    将 token 写入常见的环境变量，供依赖库使用。

    Returns:
        bool: True 表示设置成功，False 表示未获取到 token。
    """
    token = load_huggingface_token()
    if not token:
        return False

    for key in ("HUGGINGFACE_TOKEN", "HUGGINGFACE_HUB_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HF_TOKEN", "huggingface_token", "huggingfacetoken"):
        os.environ[key] = token
    logging.info("✅ HuggingFace 环境变量已完成配置")
    return True


if __name__ == "__main__":
    print("🔧 正在加载 HuggingFace token...")
    token = load_huggingface_token()
    if token:
        print(f"✅ Token 读取成功: {token[:10]}...")
        if setup_huggingface_environment():
            print("✅ 环境变量配置成功")
        else:
            print("⚠️ 环境变量配置失败")
    else:
        print("⚠️ Token 读取失败")
