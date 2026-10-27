"""Facade for the rich progress widgets used by the interest GUI.

Implementation lives in :mod:`acfv.features.modules.beautiful_progress_widget`.
We re-export the public classes here to provide a stable import path for
callers that historically relied on :mod:`acfv.interest.modules`.
"""
from __future__ import annotations

from acfv.features.modules.beautiful_progress_widget import (  # noqa: F401
    BeautifulProgressWidget,
    ProgressStylePreview,
    SimpleBeautifulProgressBar,
)

__all__ = [
    "BeautifulProgressWidget",
    "ProgressStylePreview",
    "SimpleBeautifulProgressBar",
]
