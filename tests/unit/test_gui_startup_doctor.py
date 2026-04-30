from __future__ import annotations

import sys
import types

from acfv.app import gui
from acfv.app import gui_startup_doctor as doctor


class _Config:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)


def test_collect_startup_issues_checks_ffmpeg_and_asr(monkeypatch):
    monkeypatch.setattr(doctor, "create_background_runtime", lambda log_level="INFO": object())
    monkeypatch.setattr(doctor, "_ffmpeg_available", lambda: False)
    monkeypatch.setattr(
        doctor,
        "_module_available",
        lambda name: False,
    )

    issues = doctor.collect_startup_issues(_Config({"WHISPER_ENGINE": "auto"}))
    keys = {issue.key for issue in issues}

    assert "ffmpeg" in keys
    assert "asr_auto" in keys


def test_collect_auto_fix_packages_deduplicates():
    issues = [
        doctor.StartupIssue("a", "A", "detail", can_auto_fix=True, packages=("openai-whisper",)),
        doctor.StartupIssue("b", "B", "detail", can_auto_fix=True, packages=("openai-whisper", "transformers")),
        doctor.StartupIssue("c", "C", "detail", can_auto_fix=False, packages=("faster-whisper",)),
    ]

    assert doctor.collect_auto_fix_packages(issues) == ["openai-whisper", "transformers"]


def test_run_startup_self_check_rechecks_after_install(monkeypatch):
    config = _Config(
        {
            "GUI_STARTUP_SELF_CHECK": True,
            "GUI_AUTO_INSTALL_MISSING_DEPS": True,
        }
    )
    calls = {"count": 0}

    first_issue = doctor.StartupIssue(
        "openai_whisper",
        "缺少 openai-whisper",
        "detail",
        can_auto_fix=True,
        packages=("openai-whisper",),
    )

    def _fake_collect(cfg):
        calls["count"] += 1
        return [first_issue] if calls["count"] == 1 else []

    monkeypatch.setattr(doctor, "collect_startup_issues", _fake_collect)
    monkeypatch.setattr(doctor, "install_missing_python_packages", lambda packages: (True, "ok"))

    report = doctor.run_startup_self_check(config)

    assert report.installed_packages == ["openai-whisper"]
    assert report.issues == []
    assert calls["count"] == 2


def test_launch_gui_runs_startup_self_check_and_warns(monkeypatch):
    shown: dict[str, object] = {}
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)

    class _DummyWindow:
        def show(self):
            shown["shown"] = True

    class _DummyApp:
        def __init__(self, argv):
            shown["argv"] = argv

        def exec_(self):
            return 0

    class _DummyMessageBox:
        @staticmethod
        def warning(parent, title, message):
            shown["warning"] = (title, message)

    qtwidgets = types.SimpleNamespace(
        QApplication=_DummyApp,
        QMessageBox=_DummyMessageBox,
    )
    pyqt = types.ModuleType("PyQt5")
    pyqt.QtWidgets = qtwidgets

    startup_module = types.ModuleType("acfv.app.gui_startup_doctor")
    startup_module.run_startup_self_check = lambda cfg, **kwargs: doctor.StartupCheckReport(
        issues=[doctor.StartupIssue("ffmpeg", "未检测到 ffmpeg", "detail")]
    )
    startup_module.format_startup_report = lambda report: "startup warning"
    startup_module.collect_auto_fix_packages = lambda issues: []

    interest_module = types.ModuleType("acfv.app.interest_adapter")
    interest_module.create_interest_main_window = lambda: _DummyWindow()

    config_module = types.ModuleType("acfv.config")
    config_module.ConfigManager = lambda: _Config()

    monkeypatch.setitem(sys.modules, "PyQt5", pyqt)
    monkeypatch.setitem(sys.modules, "acfv.app.gui_startup_doctor", startup_module)
    monkeypatch.setitem(sys.modules, "acfv.app.interest_adapter", interest_module)
    monkeypatch.setitem(sys.modules, "acfv.config", config_module)

    assert gui.launch_gui() == 0
    assert shown["warning"] == ("启动自检", "startup warning")
    assert shown["shown"] is True
