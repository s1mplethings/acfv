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
        # Fallback placeholder
        win = QtWidgets.QMainWindow()
        win.setWindowTitle("ACFV (Fallback GUI)")
        win.resize(680, 420)
        central = QtWidgets.QWidget(); layout = QtWidgets.QVBoxLayout(central)
        label = QtWidgets.QLabel("未能加载完整 interest_rating GUI\nFallback 原因: %s" % (integration_error or "未知"))
        label.setWordWrap(True)
        layout.addWidget(label)
        win.setCentralWidget(central)
    win.show()
    return app.exec_()
