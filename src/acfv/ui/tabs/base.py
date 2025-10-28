"""Shared dataclasses for tab factories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PyQt5.QtWidgets import QWidget


@dataclass
class TabHandle:
    title: str
    widget: QWidget
    controller: Any

