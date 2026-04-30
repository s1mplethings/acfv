from __future__ import annotations

import pytest


class _Config:
    def __init__(self):
        self.values = {
            "ENABLE_LLM_HIGHLIGHT": True,
            "ENABLE_LLM_LOCAL_DISTILL": True,
            "LLM_HIGHLIGHT_CANDIDATE_MULTIPLIER": 5,
            "LLM_HIGHLIGHT_MODEL": "gemini-2.5-flash",
            "LLM_LOCAL_MODEL": "qwen2.5:7b-instruct",
            "LLM_VISION_MODEL": "gpt-4.1-mini",
        }

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value, persist=False):
        self.values[key] = value

    def save_config(self):
        return True


def test_settings_dialog_hides_redundant_llm_fields():
    pytest.importorskip("PyQt5.QtWidgets")
    from PyQt5 import QtWidgets
    from acfv.features.modules.ui_components import SettingsDialog

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    dialog = SettingsDialog(_Config())
    try:
        assert hasattr(dialog, "remote_model_edit")
        assert not hasattr(dialog, "local_model_edit")
        assert not hasattr(dialog, "vision_model_edit")
    finally:
        dialog.deleteLater()
        app.processEvents()


def test_subtitle_render_widget_hides_redundant_llm_fields():
    pytest.importorskip("PyQt5.QtWidgets")
    from PyQt5 import QtWidgets
    from acfv.ui.tabs.subtitle_render_tab import SubtitleRenderWidget

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    widget = SubtitleRenderWidget(_Config())
    try:
        assert hasattr(widget, "edit_remote_llm_model")
        assert not hasattr(widget, "edit_local_llm_model")
        assert not hasattr(widget, "edit_remote_vision_model")
    finally:
        widget.deleteLater()
        app.processEvents()
