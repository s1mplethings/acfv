#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
静默退出模块
确保程序在打包后退出时不会产生任何控制台输出
"""

import os
import sys
import atexit
import signal
import threading
import time

class SilentExit:
    """静默退出处理器"""
    
    def __init__(self):
        self.is_packaged = hasattr(sys, '_MEIPASS')
        self.exit_handlers = []
        self.cleanup_complete = False
        
        if self.is_packaged:
            self.setup_silent_exit()
    
    def setup_silent_exit(self):
        """设置静默退出"""
        # 注册退出处理器
        atexit.register(self.silent_cleanup)
        
        # 设置信号处理器
        try:
            signal.signal(signal.SIGINT, self.signal_handler)
            signal.signal(signal.SIGTERM, self.signal_handler)
        except (AttributeError, OSError):
            # Windows可能不支持某些信号
            pass
    
    def signal_handler(self, signum, frame):
        """信号处理器"""
        if self.is_packaged:
            # 打包后静默处理信号
            self.silent_cleanup()
            sys.exit(0)
        else:
            # 开发环境正常处理
            print(f"收到信号 {signum}")
            sys.exit(0)
    
    def silent_cleanup(self):
        """静默清理"""
        if self.cleanup_complete:
            return
        
        self.cleanup_complete = True
        
        try:
            # 停止所有后台线程
            self.stop_background_threads()
            
            # 清理资源
            self.cleanup_resources()
            
            # 强制垃圾回收
            import gc
            gc.collect()
            
        except Exception:
            # 静默忽略所有清理错误
            pass
    
    def stop_background_threads(self):
        """停止后台线程"""
        try:
            # 获取所有活跃线程
            active_threads = threading.enumerate()
            
            for thread in active_threads:
                if thread != threading.main_thread() and thread.is_alive():
                    try:
                        # 尝试优雅地停止线程
                        if hasattr(thread, '_stop'):
                            thread._stop()
                    except Exception:
                        pass
        except Exception:
            pass
    
    def cleanup_resources(self):
        """清理资源"""
        try:
            # 关闭所有打开的文件
            import gc
            for obj in gc.get_objects():
                try:
                    if hasattr(obj, 'close') and callable(obj.close):
                        obj.close()
                except Exception:
                    pass
        except Exception:
            pass
    
    def add_exit_handler(self, handler):
        """添加退出处理器"""
        self.exit_handlers.append(handler)
    
    def register_exit_handlers(self):
        """注册所有退出处理器"""
        for handler in self.exit_handlers:
            try:
                atexit.register(handler)
            except Exception:
                pass

# 全局静默退出实例
silent_exit = SilentExit()

def setup_silent_exit():
    """设置静默退出"""
    if hasattr(sys, '_MEIPASS'):
        # 在打包后的环境中，重定向所有输出
        class NullOutput:
            def write(self, text): pass
            def flush(self): pass
            def close(self): pass
        
        null_output = NullOutput()
        sys.stdout = null_output
        sys.stderr = null_output
        
        # 禁用内置函数
        import builtins
        builtins.print = lambda *args, **kwargs: None
        builtins.input = lambda prompt="": ""
        builtins.help = lambda *args, **kwargs: None
        
        # 设置环境变量
        os.environ['PYTHONUNBUFFERED'] = '0'
        os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

# 在模块导入时立即设置
setup_silent_exit()
