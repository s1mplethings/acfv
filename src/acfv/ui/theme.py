"""Global palette helpers for the Qt client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PyQt5 import QtGui


@dataclass(frozen=True)
class AppPalette:
    """Simple palette definition so we can tweak colors centrally."""

    window: str = "#f5f7fb"
    base: str = "#ffffff"
    text: str = "#111827"
    subtle_text: str = "#6b7280"
    accent: str = "#3b82f6"
    border: str = "#d5d9e0"
    success: str = "#16a34a"
    warning: str = "#eab308"
    danger: str = "#ef4444"


def _color(value: str) -> QtGui.QColor:
    col = QtGui.QColor()
    col.setNamedColor(value)
    return col


def apply_app_palette(app, palette: Optional[AppPalette] = None) -> None:
    """Install a consistent palette for the entire QApplication."""
    palette = palette or AppPalette()
    qt_palette = QtGui.QPalette()
    qt_palette.setColor(QtGui.QPalette.Window, _color(palette.window))
    qt_palette.setColor(QtGui.QPalette.Base, _color(palette.base))
    qt_palette.setColor(QtGui.QPalette.AlternateBase, _color("#f0f2f7"))
    qt_palette.setColor(QtGui.QPalette.Text, _color(palette.text))
    qt_palette.setColor(QtGui.QPalette.Button, _color("#e5edff"))
    qt_palette.setColor(QtGui.QPalette.ButtonText, _color(palette.text))
    qt_palette.setColor(QtGui.QPalette.ToolTipBase, _color("#f9fafb"))
    qt_palette.setColor(QtGui.QPalette.ToolTipText, _color(palette.text))
    app.setPalette(qt_palette)


def card_frame_style(palette: Optional[AppPalette] = None) -> str:
    """Return a stylesheet string that applies a soft card look."""
    palette = palette or AppPalette()
    return (
        "QWidget#Card {"
        f"background-color: {palette.base};"
        f"border: 1px solid {palette.border};"
        "border-radius: 10px;"
        "padding: 12px;"
        "}"
        "QLabel#SectionTitle {"
        "font-size: 16px;"
        "font-weight: 600;"
        f"color: {palette.text};"
        "}"
        "QLabel#SectionSubtitle {"
        "font-size: 12px;"
        f"color: {palette.subtle_text};"
        "}"
        "QPushButton {"
        "border-radius: 6px;"
        f"background-color: {palette.accent};"
        "color: #ffffff;"
        "padding: 6px 14px;"
        "}"
        "QPushButton:disabled {"
        "background-color: #e5e7eb;"
        "color: #9ca3af;"
        "}"
    )
