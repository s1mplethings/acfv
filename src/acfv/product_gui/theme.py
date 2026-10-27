"""Central GUI design tokens and component styles."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tokens:
    bg: str = "#0b0d12"
    panel: str = "#121620"
    panel_alt: str = "#171c28"
    raised: str = "#1d2432"
    border: str = "#293244"
    text: str = "#f4f6fb"
    muted: str = "#98a2b3"
    accent: str = "#7c5cff"
    accent_hover: str = "#9278ff"
    success: str = "#32c48d"
    warning: str = "#f5b942"
    danger: str = "#ff6577"
    info: str = "#55b9ff"
    s1: int = 4
    s2: int = 8
    s3: int = 12
    s4: int = 16
    s5: int = 24
    s6: int = 32
    radius: int = 10


TOKENS = Tokens()


def stylesheet() -> str:
    t = TOKENS
    return f"""
    QWidget {{
        background: {t.bg}; color: {t.text}; font-family: "Segoe UI", "Microsoft YaHei UI";
        font-size: 13px;
    }}
    QMainWindow, QDialog {{ background: {t.bg}; }}
    QLabel[muted="true"] {{ color: {t.muted}; }}
    QLabel[role="pageTitle"] {{ font-size: 24px; font-weight: 650; }}
    QLabel[role="sectionTitle"] {{ font-size: 16px; font-weight: 600; }}
    QLabel[role="badge"] {{
        border-radius: 8px; padding: 3px 8px; background: {t.raised}; color: {t.muted};
    }}
    QLabel[state="ready"] {{ color: {t.success}; }}
    QLabel[state="warning"] {{ color: {t.warning}; }}
    QLabel[state="failed"] {{ color: {t.danger}; }}
    QPushButton {{
        min-height: 34px; border: 1px solid {t.border}; border-radius: 8px;
        padding: 0 14px; background: {t.panel_alt};
    }}
    QPushButton:hover {{ background: {t.raised}; border-color: #46516a; }}
    QPushButton:pressed {{ background: #242c3b; }}
    QPushButton:disabled {{ color: #60697a; background: #11151d; border-color: #202634; }}
    QPushButton[primary="true"] {{ background: {t.accent}; border-color: {t.accent}; font-weight: 600; }}
    QPushButton[primary="true"]:hover {{ background: {t.accent_hover}; }}
    QPushButton[nav="true"] {{ text-align: left; padding-left: 14px; border: 0; background: transparent; }}
    QPushButton[nav="true"]:checked {{ background: {t.raised}; color: white; border-left: 3px solid {t.accent}; }}
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {t.panel_alt}; border: 1px solid {t.border}; border-radius: 8px;
        padding: 7px 10px; selection-background-color: {t.accent};
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {t.accent}; }}
    QListView, QTableView, QTreeView {{
        background: {t.panel}; alternate-background-color: {t.panel_alt}; border: 0;
        outline: 0; selection-background-color: #2a2450; selection-color: white;
    }}
    QListView::item {{ border-radius: 8px; padding: 6px; margin: 2px; }}
    QListView#RecordingGrid::item {{
        background: {t.panel_alt}; border: 1px solid {t.border}; border-radius: 10px;
        padding: 14px; margin: 6px;
    }}
    QListView#RecordingGrid::item:selected {{ background: #2a2450; border-color: {t.accent}; }}
    QListView#MomentList::item, QListView#ClipList::item {{
        background: {t.panel_alt}; border: 1px solid {t.border}; padding: 10px; margin: 4px;
    }}
    QListView#MomentList::item:selected, QListView#ClipList::item:selected {{
        background: #2a2450; border-color: {t.accent};
    }}
    QHeaderView::section {{ background: {t.panel_alt}; color: {t.muted}; border: 0; padding: 8px; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: #394258; border-radius: 5px; min-height: 28px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QFrame[card="true"] {{ background: {t.panel}; border: 1px solid {t.border}; border-radius: {t.radius}px; }}
    QFrame[error="true"] {{ background: #29151b; border: 1px solid #6d2937; border-radius: {t.radius}px; }}
    QProgressBar {{ background: {t.panel_alt}; border: 0; border-radius: 4px; height: 8px; text-align: center; }}
    QProgressBar::chunk {{ background: {t.accent}; border-radius: 4px; }}
    QSplitter::handle {{ background: {t.border}; width: 1px; height: 1px; }}
    QToolTip {{ background: {t.raised}; color: {t.text}; border: 1px solid {t.border}; padding: 5px; }}
    """
