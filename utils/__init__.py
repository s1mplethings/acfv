"""Compatibility facade mapping ``utils`` to :mod:`acfv.utils`."""
from __future__ import annotations

import importlib
import sys

_pkg = importlib.import_module("acfv.utils")
sys.modules[__name__] = _pkg
