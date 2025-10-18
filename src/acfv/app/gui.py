"""GUI launcher.

Phase 1 logic:
 1. Try to launch full interest_rating MainWindow via adapter.
 2. Fallback to minimal placeholder window if integration fails or PyQt5 missing.
"""

from __future__ import annotations

def launch_gui():  # pragma: no cover - interactive GUI
    try:
        from PyQt5 import QtWidgets
    except Exception as e:  # noqa: BLE001
        print("[acfv] PyQt5 未安装或加载失败:", e)
        print("请先执行: pip install PyQt5")
        return 1

    import sys

    app = QtWidgets.QApplication(sys.argv)

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
