import os, sys, ctypes, tempfile, logging, atexit

APP_NAME = "ACFV"
LOCK_NAME = f"{APP_NAME}.lock"
LOG_DIR = os.path.join(os.getenv("LOCALAPPDATA", tempfile.gettempdir()), APP_NAME, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(filename=os.path.join(LOG_DIR, "acfv.log"),
                    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# 保留控制台：便于实时查看 stdout/stderr 日志，排查启动/切片进度。
# 如需静默，可在打包时显式传 --noconsole 或设置环境变量 ACFV_DISABLE_STDIO=1。

_lock_fp = None

def _acquire_lock():
    global _lock_fp
    lock_path = os.path.join(tempfile.gettempdir(), LOCK_NAME)
    _lock_fp = open(lock_path, "w")
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(_lock_fp.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(_lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except Exception:
        return False

def _release_lock():
    try:
        if _lock_fp:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(_lock_fp.fileno(), msvcrt.LK_UNLCK, 1)
            _lock_fp.close()
    except Exception:
        pass

atexit.register(_release_lock)

def _run_gui():
    # Prefer GUI entry; fallback到包的 __main__。
    try:
        from acfv.app.gui import main as gui_main
        return gui_main()
    except Exception:
        from acfv import __main__ as app_main
        return app_main.main()

def main():
    if not _acquire_lock():
        sys.exit(0)
    try:
        logging.info("ACFV launcher start")
        # 确保 stdout/stderr 指向控制台（若存在）
        try:
            if hasattr(sys, "stdout") and sys.stdout is None:
                sys.stdout = sys.__stdout__
            if hasattr(sys, "stderr") and sys.stderr is None:
                sys.stderr = sys.__stderr__
        except Exception:
            pass
        _run_gui()
    except Exception as e:
        logging.exception("ACFV launcher error: %s", e)
        try:
            ctypes.windll.user32.MessageBoxW(None, f"ACFV 出错：{e}", "ACFV", 0x00000010)
        except Exception:
            pass

if __name__ == "__main__":
    main()
