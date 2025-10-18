def main(*args):
    """启动 ACFV GUI 主窗口"""
    try:
        from acfv.app.gui import launch_gui
        return launch_gui()
    except ImportError as e:
        print(f"[acfv] GUI 依赖缺失: {e}")
        print("请安装 GUI 依赖: pip install PyQt5")
        return 1
    except Exception as e:
        print(f"[acfv] GUI 启动失败: {e}")
        return 1
