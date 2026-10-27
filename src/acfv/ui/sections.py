"""Composable layout helpers for building consistent cards/headers."""

from __future__ import annotations

from typing import Optional

from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget


def build_section_header(title: str, subtitle: Optional[str] = None) -> QWidget:
    """Return a QWidget containing styled title/subtitle labels."""
    wrapper = QWidget()
    wrapper.setObjectName("Card")
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)

    title_label = QLabel(title)
    title_label.setObjectName("SectionTitle")
    layout.addWidget(title_label)

    if subtitle:
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("SectionSubtitle")
        layout.addWidget(subtitle_label)

    return wrapper


def wrap_in_card(widget: QWidget) -> QWidget:
    """Nest another widget inside a styled card container."""
    card = QWidget()
    card.setObjectName("Card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.addWidget(widget)
    return card

