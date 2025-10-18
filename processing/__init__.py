"""Compatibility facade for legacy imports.

Legacy modules still import ``processing.*``.  We transparently forward those
imports to the refactored package under :mod:`acfv.processing`.
"""
from __future__ import annotations

import importlib
import sys

_pkg = importlib.import_module("acfv.processing")
sys.modules[__name__] = _pkg
