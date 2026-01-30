#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
视频处理工具 - 完整启动代码
模块化版本 v2.0

功能特性：
- Twitch直播回放下载
- 本地视频处理和分析
- AI智能切片生成
- 切片评分和管理
- 断点续传支持
"""

# ⚡ 在导入任何库之前设置环境变量解决OpenMP冲突
import os
os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'  # 解决OpenMP库冲突
os.environ['OMP_NUM_THREADS'] = '1'  # 限制OpenMP线程数
os.environ['PYTHONWARNINGS'] = 'ignore::FutureWarning,ignore::UserWarning'

# 🔧 设置跳过重依赖检查以解决numpy兼容性问题
os.environ['SKIP_HEAVY_CHECKS'] = '1'  # 跳过可能导致崩溃的重依赖检查

# 🚫 控制台抑制（仅在显式要求时）
def maybe_disable_console():
    """
    原行为：打包环境直接吞掉 stdout/stderr。
    新要求：所有 GUI/CLI 进度必须可见于终端，因此默认不再抑制。
    若确需静默（CI/后台），设置环境变量 ACFV_DISABLE_STDIO=1。
    """
    try:
        if os.environ.get("ACFV_DISABLE_STDIO") != "1":
            return
        class NullDevice:
            def write(self, text): pass
            def flush(self): pass
            def close(self): pass
            def fileno(self): return -1
            def isatty(self): return False
            def readable(self): return False
            def writable(self): return False
            def seekable(self): return False
            def read(self, size=-1): return ""
            def readline(self, size=-1): return ""
            def readlines(self, size=-1): return []
            def writelines(self, lines): pass
            def __enter__(self): return self
            def __exit__(self, exc_type, exc_val, exc_tb): pass
        null_dev = NullDevice()
        sys.stdout = null_dev
        sys.stderr = null_dev
        sys.stdin = null_dev
    except Exception:
        pass

# 默认不禁用，除非显式设置 ACFV_DISABLE_STDIO=1
maybe_disable_console()

import sys
import json
import logging
import traceback
import time
import gc
import signal
import atexit
import warnings
from datetime import datetime

# 项目根目录，所有路径引用都用 BASE_DIR 拼接
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 过滤掉常见的第三方库警告
warnings.filterwarnings("ignore", category=FutureWarning, module="torch.*")
warnings.filterwarnings("ignore", category=UserWarning, module="whisper.*")
warnings.filterwarnings("ignore", message=".*torch.distributed.reduce_op.*")
warnings.filterwarnings("ignore", message=".*Failed to launch Triton kernels.*")

# 添加必要的导入
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# 添加当前目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# 导入警告管理器（必须在其他模块之前）
try:
    try:
        from acfv.warning_manager import setup_warning_filters, with_suppressed_warnings  # type: ignore
    except Exception:  # noqa: BLE001
        def setup_warning_filters():
            pass
        def with_suppressed_warnings():
            from contextlib import contextmanager
            @contextmanager
            def _cm():
                yield
            return _cm()
    setup_warning_filters()
except ImportError:
    # 如果警告管理器不可用，使用内置的警告过滤
    warnings.filterwarnings("ignore", category=FutureWarning, module="torch.*")
    warnings.filterwarnings("ignore", category=UserWarning, module="whisper.*")

def setup_logging():
    """设置日志系统 - 支持环境变量控制"""
    from acfv.features.modules.core import LogManager
    
    # 创建logs目录
    log_dir = os.path.join(current_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    # 根据环境变量设置日志级别
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    
    # 使用日志管理器设置日志系统
    log_manager = LogManager()
    result = log_manager.setup_logging(log_dir, "video_processor")
    
    # 获取root logger来设置日志级别
    root_logger = logging.getLogger()
    
    # 设置日志级别
    if log_level == 'DEBUG':
        root_logger.setLevel(logging.DEBUG)
    elif log_level == 'INFO':
        root_logger.setLevel(logging.INFO)
    elif log_level == 'WARNING':
        root_logger.setLevel(logging.WARNING)
    else:
        root_logger.setLevel(logging.INFO)
    
    return log_manager

def check_python_version():
    """检查Python版本"""
    if sys.version_info < (3, 7):
        print("❌ 错误: 需要Python 3.7或更高版本")
        print(f"当前版本: {sys.version}")
        return False
    
    print(f"✓ Python版本检查通过: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    return True

def check_dependencies():
    """检查必要的依赖包 - 快速版本"""
    # 检查是否跳过重检查
    if os.environ.get('SKIP_HEAVY_CHECKS', '0') == '1':
        try:
            __import__('PyQt5')
            return True
        except ImportError:
            print("❌ 缺少 PyQt5，请安装: pip install PyQt5")
            return False
    
    # 只检查最关键的PyQt5，其他延迟检查
    try:
        __import__('PyQt5')
        print("✓ 核心依赖检查通过，其他依赖将按需加载")
        return True
    except ImportError:
        print("❌ 缺少 PyQt5，请安装: pip install PyQt5")
        return False

def check_heavy_dependencies():
    """延迟检查重依赖包 - 简化版本"""
    # 在跳过模式下静默检查，不输出详细信息
    if os.environ.get('SKIP_HEAVY_CHECKS', '0') == '1':
        return True
    
    # 简单检查模式 - 增加numpy兼容性处理
    missing = []
    for module in ['cv2', 'numpy', 'sklearn']:
        try:
            if module == 'numpy':
                # 特殊处理numpy兼容性问题
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    import numpy
                    # 测试numpy是否可用
                    numpy.array([1, 2, 3])
            else:
                __import__(module)
        except ImportError:
            missing.append(module)
        except Exception as e:
            # numpy兼容性问题，但仍可使用
            if module == 'numpy' and 'dtype size changed' in str(e):
                logging.warning(f"Numpy兼容性警告，但仍可继续使用: {e}")
            else:
                logging.error(f"模块 {module} 加载失败: {e}")
    
    if missing and os.environ.get('LOG_LEVEL', 'INFO') == 'DEBUG':
        print(f"⚠️ 缺少模块: {missing}，将在需要时提示安装")
    
    return True

def initialize_directories():
    """初始化必要的目录结构 - 简化版本"""
    # 只创建最必要的目录
    essential_directories = [
        "logs",                # 日志文件
        "processing"           # 处理过程中的临时文件
    ]
    
    for directory in essential_directories:
        try:
            full_path = os.path.join(current_dir, directory)
            os.makedirs(full_path, exist_ok=True)
        except Exception as e:
            logging.error(f"创建目录 {directory} 失败: {e}")
            return False
    
    return True

def create_default_config():
    """创建默认配置文件 - 简化版本"""
    from acfv.runtime.storage import settings_path
    config_file = str(settings_path("config.json"))
    
    # 如果配置文件已存在，跳过创建
    if os.path.exists(config_file):
        return True
    
    # 最小化配置
    default_config = {
        "CLIPS_BASE_DIR": "clips",
        "MAX_CLIP_COUNT": 10,
        "WHISPER_MODEL": "base",  # 使用更小的模型
        "ENABLE_VIDEO_EMOTION": False,
        "MAX_WORKERS": 2  # 减少工作线程数
    }
    
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logging.error(f"创建配置文件失败: {e}")
        return False

def initialize_video_mapping():
    """初始化视频映射文件"""
    mapping_file = os.path.join(current_dir, "processing", "video_mappings.json")
    
    if not os.path.exists(mapping_file):
        try:
            with open(os.path.join(BASE_DIR, "data", "video_mappings.json"), 'w', encoding='utf-8') as f:
                json.dump({}, f)
            print("  ✓ 视频映射文件已创建")
        except Exception as e:
            print(f"  ✗ 创建视频映射文件失败: {e}")
            return False
    
    return True



def cleanup_all_threads():
    """强健的线程清理函数"""
    import logging
    import gc
    
    logging.info("开始清理线程...")
    try:
        # 导入必要的Qt模块
        from PyQt5.QtCore import QThread
        from PyQt5.QtWidgets import QApplication
        
        # 获取QApplication实例
        app = QApplication.instance()
        if app:
            # 处理待处理的事件
            try:
                app.processEvents()
            except Exception:
                pass
        
        # 为避免 "QThread: Destroyed while thread is still running"，这里不再遍历并强制终止所有QThread
        # 交由各模块的 cleanup/stop 自行优雅处理，避免在 aboutToQuit 阶段误删仍在运行的线程对象
        logging.info("跳过全量QThread强制清理，改为依赖模块级清理")
        
        # 强制垃圾回收
        gc.collect()
        
        # 处理待处理的Qt事件
        if app:
            try:
                app.processEvents()
            except Exception:
                pass
            
    except Exception as e:
        logging.debug(f"线程清理时忽略错误: {e}")
        
    logging.info("线程清理完成")

def safe_subprocess_run(*args, **kwargs):
    """
    安全的subprocess运行函数，自动处理Windows编码问题
    """
    import subprocess
    
    # 如果设置了text=True，确保有正确的编码设置
    if kwargs.get('text', False):
        kwargs.setdefault('encoding', 'utf-8')
        kwargs.setdefault('errors', 'ignore')
    
    return subprocess.run(*args, **kwargs)

def force_terminate_processes():
    """直接kill所有相关进程"""
    import logging
    
    logging.info("开始进程清理...")
    try:
        import psutil
        current_pid = os.getpid()
        
        # 获取当前进程的所有子进程并kill
        try:
            current_process = psutil.Process(current_pid)
            children = current_process.children(recursive=True)
            
            if not children:
                logging.info("未发现子进程")
                return
                
            logging.info(f"发现 {len(children)} 个子进程，直接清理")
            
            for child in children:
                try:
                    child.kill()
                except:
                    pass
                    
            logging.info("子进程清理完成")
                    
        except Exception as e:
            logging.debug(f"清理子进程时忽略错误: {e}")
            
    except ImportError:
        logging.info("psutil不可用，跳过子进程清理")

# 🆕 统一且可重入的全局清理函数，避免重复清理
_cleanup_has_run = False

def global_cleanup():
    import logging
    global _cleanup_has_run
    if _cleanup_has_run:
        if not hasattr(sys, '_MEIPASS'):
            logging.info("清理已执行，跳过重复调用")
        return
    _cleanup_has_run = True
    
    # 在打包后的环境中，静默清理
    if hasattr(sys, '_MEIPASS'):
        # 静默清理，不记录日志
        pass
    else:
        logging.info("程序退出，开始清理...")
    
    try:
        cleanup_all_threads()
        force_terminate_processes()
    except Exception as e:
        # 静默处理清理错误
        if not hasattr(sys, '_MEIPASS'):
            logging.debug(f"清理时忽略错误: {e}")


# 🆕 快速退出：强制终止子进程并立刻退出进程（通过环境变量 FAST_EXIT 控制）
def fast_exit(code: int = 0):
    import logging
    logging.info("快速退出：直接终止所有子进程并立即退出")
    try:
        force_terminate_processes()
    except Exception as e:
        logging.debug(f"快速退出时忽略错误: {e}")
    os._exit(code)


def exception_hook(exc_type, exc_value, exc_traceback):
    """改进的全局异常处理钩子"""
    import logging
    
    if issubclass(exc_type, KeyboardInterrupt):
        # 用户中断
        logging.info("用户中断程序")
    elif issubclass(exc_type, MemoryError):
        # 内存错误
        logging.critical("内存不足错误", exc_info=True)
    elif issubclass(exc_type, ImportError):
        # 导入错误
        logging.error("模块导入错误", exc_info=True)
    elif issubclass(exc_type, (OSError, IOError)):
        # 文件系统错误
        logging.error("文件系统错误", exc_info=True)
    elif 'access violation' in str(exc_value) or 'segmentation fault' in str(exc_value).lower():
        # Windows访问违规或Linux段错误，通常是C++库崩溃
        logging.critical("检测到内存访问违规，可能是多线程UI更新冲突", exc_info=True)
        # 对于这类崩溃，尝试优雅清理但不阻塞
        try:
            global_cleanup()
        except Exception:
            pass
        os._exit(1)  # 立即退出，避免进一步损坏
    else:
        # 其他未捕获的异常
        logging.error("未捕获的异常", exc_info=True)
        # 输出详细错误信息到控制台
        print(f"ERROR: 未捕获的异常: {exc_type.__name__}: {exc_value}")
        print(f"异常位置: {exc_traceback}")
        import traceback
        traceback.print_exception(exc_type, exc_value, exc_traceback)
    
    # 使用统一清理，或启用快速退出
    if os.environ.get('FAST_EXIT', '0') == '1':
        fast_exit(1)
    else:
        global_cleanup()
    
    # 退出程序
    import sys
    sys.exit(1)

def print_welcome():
    """打印欢迎信息 - 简化版本"""
    # 在打包后的环境中，不显示欢迎信息
    if hasattr(sys, '_MEIPASS'):
        return
    
    print("🎬 视频处理工具 v2.0 - 优化启动")
    print("⚡ 快速模式：减少初始化时间，按需加载功能")
    print("-" * 50)

def setup_low_overhead_crash_handlers():
    """低开销崩溃防护与异常收敛到日志"""
    import threading
    import faulthandler
    global _CRASH_DUMP_FILE
    try:
        log_dir = os.path.join(BASE_DIR, "data", "logs")
        os.makedirs(log_dir, exist_ok=True)
        crash_path = os.path.join(log_dir, "crash_dump.log")
        # 以追加模式打开，保持句柄常驻
        _CRASH_DUMP_FILE = open(crash_path, "a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=_CRASH_DUMP_FILE, all_threads=True)
    except Exception as e:
        logging.debug(f"faulthandler 启用失败: {e}")
    
    # 线程未捕获异常 -> 日志
    try:
        def _thread_excepthook(args):
            logging.error("[thread] 未捕获异常", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        if hasattr(threading, "excepthook"):
            threading.excepthook = _thread_excepthook  # type: ignore[attr-defined]
    except Exception as e:
        logging.debug(f"threading.excepthook 设置失败: {e}")
    
    # 无法抛出的异常（析构器等）-> 日志
    try:
        def _unraisable_hook(unraisable):
            msg = getattr(unraisable, 'err_msg', '') or 'Unraisable exception'
            exc = getattr(unraisable, 'exc', None)
            tb = exc.__traceback__ if exc else None
            logging.error(f"[unraisable] {msg}", exc_info=(type(exc), exc, tb))
        if hasattr(sys, "unraisablehook"):
            sys.unraisablehook = _unraisable_hook  # type: ignore[attr-defined]
    except Exception as e:
        logging.debug(f"sys.unraisablehook 设置失败: {e}")
    
    # 退出时关闭转储文件
    try:
        def _close_crash_dump_file():
            global _CRASH_DUMP_FILE
            try:
                if _CRASH_DUMP_FILE and not _CRASH_DUMP_FILE.closed:
                    _CRASH_DUMP_FILE.flush()
                    _CRASH_DUMP_FILE.close()
            except Exception:
                pass
        atexit.register(_close_crash_dump_file)
    except Exception:
        pass


def set_windows_error_mode():
    """禁用 Windows 错误对话框（低开销）"""
    try:
        if sys.platform.startswith('win'):
            import ctypes
            SEM_FAILCRITICALERRORS = 0x0001
            SEM_NOGPFAULTERRORBOX = 0x0002
            SEM_NOOPENFILEERRORBOX = 0x8000
            ctypes.windll.kernel32.SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX)
    except Exception as e:
        logging.debug(f"SetErrorMode 设置失败: {e}")


def setup_qt_message_logging():
    """把 Qt 的输出统一到 Python logging（低开销）"""
    try:
        from PyQt5.QtCore import qInstallMessageHandler, QtMsgType
        def handler(mode, context, message):
            try:
                if mode in (QtMsgType.QtFatalMsg,):
                    logging.critical(f"[QtFatal] {message}")
                elif mode in (QtMsgType.QtCriticalMsg,):
                    logging.error(f"[QtCritical] {message}")
                elif mode in (QtMsgType.QtWarningMsg,):
                    logging.warning(f"[QtWarning] {message}")
                elif mode in (QtMsgType.QtInfoMsg,):
                    logging.info(f"[QtInfo] {message}")
                else:
                    logging.debug(f"[QtDebug] {message}")
            except Exception:
                pass
        qInstallMessageHandler(handler)
    except Exception as e:
        logging.debug(f"Qt 消息日志处理器设置失败: {e}")


def main():
    """主函数"""
    # 设置全局异常处理
    sys.excepthook = exception_hook
    
    # 设置信号处理
    def signal_handler(signum, frame):
        logging.info(f"收到信号 {signum}，开始清理...")
        # 统一清理，或启用快速退出
        if os.environ.get('FAST_EXIT', '0') == '1':
            fast_exit(0)
        else:
            # 统一清理，确保只执行一次
            global_cleanup()
            sys.exit(0)
    
    # 只在支持的系统上设置信号处理
    try:
        signal.signal(signal.SIGINT, signal_handler)
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, signal_handler)
    except (AttributeError, OSError) as e:
        logging.debug(f"信号处理设置失败（可能在Windows上）: {e}")
    
    try:
        # 设置日志系统
        setup_logging()
        
        # 低开销崩溃/异常收敛
        setup_low_overhead_crash_handlers()
        set_windows_error_mode()
        
        # 检查Python版本
        if not check_python_version():
            sys.exit(1)
        
        # 检查基本依赖
        if not check_dependencies():
            sys.exit(1)
        
        # 初始化目录
        initialize_directories()
        
        # 创建默认配置（轻量，保持同步执行以供窗口读取）
        create_default_config()

        # 初始化视频映射（轻量 IO，保持同步避免并发竞态）
        initialize_video_mapping()

        # 打印欢迎信息
        print_welcome()

        # 首先创建QApplication - 这是关键！
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QIcon
        app = QApplication(sys.argv)

        # 安装 Qt 日志处理器（低开销）
        setup_qt_message_logging()

        # 设置应用程序退出时的清理
        def cleanup_on_exit():
            # 路由到统一的全局清理（带防重入），或启用快速退出
            if os.environ.get('FAST_EXIT', '0') == '1':
                fast_exit(0)
            else:
                global_cleanup()

        app.aboutToQuit.connect(cleanup_on_exit)

        def init_config_manager():
            try:
                from acfv.config.config import ConfigManager
                config_manager = ConfigManager()
                return config_manager
            except Exception as e:
                logging.error(f"配置管理器初始化失败: {e}")
                return None
        
        def create_main_window(config_manager):
            try:
                from acfv.main_window import MainWindow
                return MainWindow(config_manager)
            except Exception as e:
                logging.error(f"主窗口创建失败: {e}")
                return None

        def _is_truthy(value) -> bool:
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            return bool(value)
        
        config_manager = init_config_manager()
        if not config_manager:
            logging.error("配置管理器初始化失败")
            sys.exit(1)
        
        # 🆕 解析应用图标路径（优先从配置读取 APP_ICON_PATH/APP_ICON）
        def _resolve_icon_path(cfg):
            try:
                icon_key_candidates = [
                    'APP_ICON_PATH', 'APP_ICON', 'ICON_PATH'
                ]
                icon_path = None
                for k in icon_key_candidates:
                    try:
                        v = cfg.get(k)
                        if v:
                            icon_path = v
                            break
                    except Exception:
                        continue
                # 如果配置里有，优先解析
                if icon_path:
                    if os.path.isabs(icon_path) and os.path.exists(icon_path):
                        return icon_path
                    cand = os.path.join(current_dir, icon_path)
                    if os.path.exists(cand):
                        return cand
                # 常见备选路径
                fallbacks = [
                    os.path.join(current_dir, 'acfv.png'),
                    os.path.join(current_dir, 'assets', 'app.ico'),
                    os.path.join(current_dir, 'assets', 'app.png'),
                    os.path.join(current_dir, 'assets', 'acfv-logo.ico'),
                    os.path.join(current_dir, 'assets', 'acfv-logo.png'),
                    os.path.join(current_dir, 'icons', 'app.ico'),
                    os.path.join(current_dir, 'icons', 'app.png'),
                    os.path.join(current_dir, 'app.ico'),
                    os.path.join(current_dir, 'app.png'),
                    os.path.join(current_dir, 'icon.ico'),
                    os.path.join(BASE_DIR, 'config', 'icon.png'),
                ]
                for p in fallbacks:
                    if os.path.exists(p):
                        return p
            except Exception:
                pass
            return None

        icon_path = _resolve_icon_path(config_manager)

        # 设置应用程序图标（任务栏/Alt-Tab）
        if icon_path:
            try:
                app.setWindowIcon(QIcon(icon_path))
            except Exception as e:
                logging.debug(f"设置应用图标失败: {e}")

        main_window = create_main_window(config_manager)
        if not main_window:
            logging.error("主窗口创建失败")
            sys.exit(1)
        
        # 设置主窗口图标（标题栏）
        if icon_path:
            try:
                main_window.setWindowIcon(QIcon(icon_path))
            except Exception as e:
                logging.debug(f"设置窗口图标失败: {e}")

        # 显示主窗口
        main_window.show()

        # ✅ 后台进行重依赖与映射检查，避免阻塞 UI 启动
        def run_post_start_checks():
            import threading
            log = logging.getLogger("acfv.startup")

            def _worker():
                log.info("后台检查开始：重依赖/视频映射")
                try:
                    check_heavy_dependencies()
                    log.info("重依赖检查完成")
                except Exception as e:
                    log.error(f"重依赖检查失败: {e}")
                try:
                    initialize_video_mapping()
                    log.info("视频映射检查/创建完成")
                except Exception as e:
                    log.error(f"视频映射初始化失败: {e}")

            threading.Thread(target=_worker, name="post-start-checks", daemon=True).start()

        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, run_post_start_checks)

        # 可选：启动后直接转入托盘后台运行
        try:
            start_in_tray = _is_truthy(config_manager.get("START_IN_TRAY", False))
        except Exception:
            start_in_tray = False
        if start_in_tray:
            if main_window.tray_manager:
                main_window.hide()
                main_window.tray_manager.show_hidden_tip()
                logging.info("应用已启动为后台运行模式（托盘）")
            else:
                logging.info("系统托盘不可用，无法后台运行")

        # 移除了自动刷新功能，用户可以通过手动刷新按钮来更新clips列表
        logging.info("✅ 主窗口已显示，请使用刷新按钮来更新clips列表")

        # 设置程序退出时的清理（兜底，已带防重入）
        atexit.register(cleanup_on_exit)
        
        # 🆕 设置更长的退出等待时间
        import time
        
        # 运行应用程序
        exit_code = app.exec_()
        
        # 应用程序退出后，确保清理
        try:
            if hasattr(sys, '_MEIPASS'):
                # 打包后静默清理
                pass
            else:
                logging.info("应用程序已退出，开始最终清理...")
        except Exception:
            pass
        
        # 🆕 给线程更多时间完全停止
        time.sleep(1.0)
        
        # 统一清理（带防重入）
        try:
            global_cleanup()
        except Exception:
            # 静默处理清理错误
            pass
        
        # 🆕 再次等待确保所有线程都已停止
        time.sleep(0.5)
        
        return exit_code
        
    except KeyboardInterrupt:
        logging.info("收到中断信号，正在退出...")
        global_cleanup()
        return 0
    except Exception as e:
        logging.error(f"程序运行失败: {e}")
        logging.debug("详细错误信息:", exc_info=True)
        global_cleanup()
        return 1

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except Exception as e:
        # 在打包后的环境中，不显示控制台输入提示
        if hasattr(sys, '_MEIPASS'):
            # 打包后直接退出，不等待用户输入
            sys.exit(1)
        else:
            # 开发环境中显示错误信息
            print(f"\n💥 致命错误: {e}")
            traceback.print_exc()
            input("\n按回车键退出...")
            sys.exit(1)
