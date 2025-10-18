"""Compatibility wrapper for legacy imports.

The actual implementation lives in :mod:`acfv.config._config_impl`.  This module
re-exports its public surface so existing ``from acfv.config import ConfigManager``
and historical ``acfv.config.config`` paths continue to work.
"""
from __future__ import annotations

from ._config_impl import *  # noqa: F401,F403
