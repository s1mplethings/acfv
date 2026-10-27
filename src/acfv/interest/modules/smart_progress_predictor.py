"""Facade for smart progress prediction utilities used by the GUI."""
from __future__ import annotations

from acfv.features.modules.smart_progress_predictor import (  # noqa: F401
    SimplePredictor,
    SmartProgressPredictor,
)

__all__ = ["SmartProgressPredictor", "SimplePredictor"]
