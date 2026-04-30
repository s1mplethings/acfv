"""GUI launcher.

Phase 1 logic:
 1. Try to launch full interest_rating MainWindow via adapter.
 2. Fallback to minimal placeholder window if integration fails or PyQt5 missing.
"""

from __future__ import annotations

import logging
import os
import threading


LOGGER = logging.getLogger(__name__)


def _should_show_startup_dialog() -> bool:
    platform_name = os.environ.get("QT_QPA_PLATFORM", "").strip().lower()
    return platform_name not in {"offscreen", "minimal"}


def _install_missing_packages_in_background(packages: list[str]) -> None:
    if not packages:
        return

    def _worker() -> None:
        try:
            from .gui_startup_doctor import install_missing_python_packages

            ok, output = install_missing_python_packages(packages)
            if ok:
                LOGGER.info("[gui-startup] background dependency install completed: %s", ", ".join(packages))
            else:
                LOGGER.warning("[gui-startup] background dependency install failed: %s", output)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("[gui-startup] background dependency install crashed: %s", exc)

    threading.Thread(
        target=_worker,
        name="acfv-gui-startup-install",
        daemon=True,
    ).start()

def launch_gui():  # pragma: no cover - interactive GUI
    try:
        from PyQt5 import QtWidgets
    except Exception as e:  # noqa: BLE001
        print("[acfv] PyQt5 未安装或加载失败:", e)
        print("请先执行: pip install PyQt5")
        return 1

    import sys

    app = QtWidgets.QApplication(sys.argv)
    startup_report = None
    startup_error = None
    deferred_install_packages: list[str] = []
    try:
        from acfv.config import ConfigManager
        from .gui_startup_doctor import collect_auto_fix_packages, format_startup_report, run_startup_self_check

        cfg = ConfigManager()
        startup_report = run_startup_self_check(cfg, attempt_auto_fix=False)
        if startup_report and (startup_report.issues or startup_report.install_error):
            if bool(cfg.get("GUI_AUTO_INSTALL_MISSING_DEPS", True)):
                deferred_install_packages = collect_auto_fix_packages(startup_report.issues)
                if deferred_install_packages:
                    _install_missing_packages_in_background(deferred_install_packages)
            warning_text = format_startup_report(startup_report)
            if deferred_install_packages:
                warning_text = (
                    "检测到缺失依赖，已在后台尝试自动安装："
                    + ", ".join(deferred_install_packages)
                    + "\n安装完成后建议重启 GUI。\n\n"
                    + warning_text
                )
            if _should_show_startup_dialog():
                QtWidgets.QMessageBox.warning(
                    None,
                    "启动自检",
                    warning_text,
                )
            else:
                LOGGER.warning("[gui-startup] %s", warning_text.replace("\n", " | "))
    except Exception as e:  # noqa: BLE001
        startup_error = e

    # Attempt to load full interest_rating window
    win = None
    integration_error = None
    try:  # primary path
        from .interest_adapter import create_interest_main_window
        win = create_interest_main_window()
    except Exception as e:  # noqa: BLE001
        integration_error = e

    if win is None:
        # Fallback placeholder with richer diagnostics
        detail = str(integration_error or "未知")
        suggestions = []
        if "dtype size changed" in detail and "numpy" in detail.lower():
            suggestions.append(
                "检测到 numpy 二进制兼容性问题：请尝试执行如下步骤:\n"
                "1) 卸载: pip uninstall -y numpy\n"
                "2) 重新安装与当前 Python/平台匹配版本: pip install --force-reinstall numpy\n"
                "3) 若使用 conda: conda install -y numpy\n"
                "4) 若仍失败，删除本地缓存: pip cache purge"
            )
        if "No module named" in detail:
            suggestions.append("缺少依赖，请确认已在虚拟环境中安装项目 requirements: pip install -r requirements.txt")
        if startup_error is not None:
            suggestions.append(f"启动自检执行失败: {startup_error}")
        if not suggestions:
            suggestions.append("可尝试: pip install -e . 重新开发安装，或检查 Python 环境冲突。")

        msg = (
            "未能加载完整 interest_rating GUI\n"
            f"Fallback 原因: {detail}\n\n" + "\n\n".join(suggestions)
        )
        win = QtWidgets.QMainWindow()
        win.setWindowTitle("ACFV (Fallback GUI)")
        win.resize(760, 480)
        central = QtWidgets.QWidget(); layout = QtWidgets.QVBoxLayout(central)
        label = QtWidgets.QLabel(msg)
        label.setWordWrap(True)
        layout.addWidget(label)
        win.setCentralWidget(central)
    win.show()
    return app.exec_()
