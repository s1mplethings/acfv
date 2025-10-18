#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
警告管理模块
统一管理第三方库的警告过滤
"""

import warnings
import os
import logging
from typing import Set

def setup_warning_filters():
    """设置警告过滤器"""
    
    # 过滤torch相关的FutureWarning
    # Torch future deprecation messages
    warnings.filterwarnings("ignore", category=FutureWarning, module="torch.*")
    warnings.filterwarnings("ignore", message=r".*torch\.distributed\.reduce_op.*")
    warnings.filterwarnings("ignore", message=r".*torch\.distributed\.ReduceOp.*")
    warnings.filterwarnings(
        "ignore",
        category=FutureWarning,
        message=r"`torch\.distributed\.reduce_op` is deprecated",
    )
    
    # 过滤whisper相关的警告
    warnings.filterwarnings("ignore", category=UserWarning, module="whisper.*")
    warnings.filterwarnings("ignore", message=".*Failed to launch Triton kernels.*")
    warnings.filterwarnings("ignore", message=".*falling back to.*")
    
    # 过滤其他常见的第三方库警告
    warnings.filterwarnings("ignore", category=UserWarning, module="transformers.*")
    warnings.filterwarnings("ignore", category=FutureWarning, module="transformers.*")
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="pkg_resources.*")
    
    # 设置环境变量
    os.environ['PYTHONWARNINGS'] = 'ignore::FutureWarning,ignore::UserWarning'
    
    logging.debug("警告过滤器已设置")

def suppress_torch_warnings():
    """专门抑制torch相关警告"""
    try:
        import torch
        # 设置torch的警告级别
        torch.set_warn_always(False)
    except ImportError:
        pass

def with_suppressed_warnings(func):
    """装饰器：在函数执行期间抑制警告"""
    def wrapper(*args, **kwargs):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return func(*args, **kwargs)
    return wrapper

# --- One-time warning helpers -------------------------------------------------
_emitted: Set[str] = set()

def warn_once(key: str, message: str, level: int = logging.WARNING) -> None:
    """Emit a warning log only once per process lifetime.

    Args:
        key: stable identifier for the warning type.
        message: human-readable message.
        level: logging level (default WARNING).
    """
    if key in _emitted:
        return
    _emitted.add(key)
    logging.log(level, message)

def ensure_hf_token_notice(token_present: bool) -> None:
    """Emit a single guidance message when HuggingFace token is missing."""
    if token_present:
        return
    warn_once(
        "hf_token_missing",
        "⚠️ HuggingFace token 未配置。请设置环境变量 HUGGINGFACE_TOKEN 或在 secrets/config.json 中填写 huggingface_token。",
    )

# 在模块导入时自动设置
setup_warning_filters()
suppress_torch_warnings()

if __name__ == "__main__":
    print("警告管理模块 - 已设置警告过滤器")
    print("支持的过滤:")
    print("  • torch.distributed 相关警告")
    print("  • whisper Triton kernels 警告")  
    print("  • transformers 相关警告")
    print("  • 其他常见的第三方库警告")
