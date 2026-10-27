"""Compatibility layer for historical ``acfv.config.config.config`` imports."""
from __future__ import annotations

import importlib

_impl = importlib.import_module("acfv.config._config_impl")

ConfigManager = _impl.ConfigManager
config_manager = _impl.config_manager
get_config = _impl.get_config
load_config = _impl.load_config
save_config = _impl.save_config

__all__ = [
    "ConfigManager",
    "config_manager",
    "get_config",
    "load_config",
    "save_config",
]
