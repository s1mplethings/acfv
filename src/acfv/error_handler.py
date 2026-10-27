#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
错误处理模块 - 专门用于打包后的错误处理
"""

import os
import sys
import logging
import traceback
from datetime import datetime

class PackagedErrorHandler:
    """打包后的错误处理器"""
    
    def __init__(self):
        self.is_packaged = hasattr(sys, '_MEIPASS')
        self.log_dir = None
        self.setup_logging()
    
    def setup_logging(self):
        """设置日志系统"""
        if self.is_packaged:
            try:
                # 在打包后的环境中，日志文件放在exe同目录的logs文件夹
                exe_dir = os.path.dirname(sys.executable)
                self.log_dir = os.path.join(exe_dir, 'logs')
                os.makedirs(self.log_dir, exist_ok=True)
                
                log_file = os.path.join(self.log_dir, f'error_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
                
                logging.basicConfig(
                    level=logging.ERROR,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler(log_file, encoding='utf-8'),
                        logging.StreamHandler(sys.stdout)
                    ]
                )
            except Exception as e:
                # 如果日志设置失败，至少确保不会崩溃
                pass
    
    def handle_exception(self, exc_type, exc_value, exc_traceback):
        """处理未捕获的异常"""
        if self.is_packaged:
            try:
                # 记录错误到日志文件
                error_msg = f"未捕获的异常: {exc_type.__name__}: {exc_value}"
                logging.error(error_msg)
                logging.error(f"详细错误信息:\n{traceback.format_exception(exc_type, exc_value, exc_traceback)}")
                
                # 在打包后的环境中，静默处理错误
                return
            except Exception:
                # 如果日志记录也失败，直接忽略
                pass
        else:
            # 开发环境中显示错误
            print(f"未捕获的异常: {exc_type.__name__}: {exc_value}")
            traceback.print_exception(exc_type, exc_value, exc_traceback)
    
    def handle_import_error(self, module_name):
        """处理模块导入错误"""
        if self.is_packaged:
            try:
                logging.error(f"模块导入失败: {module_name}")
                # 在打包后的环境中，尝试记录错误但不显示
                return False
            except Exception:
                return False
        else:
            print(f"模块导入失败: {module_name}")
            return False
    
    def safe_exit(self, exit_code=1):
        """安全退出程序"""
        if self.is_packaged:
            # 打包后直接退出
            try:
                logging.info(f"程序安全退出，退出码: {exit_code}")
            except Exception:
                pass
            sys.exit(exit_code)
        else:
            # 开发环境等待用户确认
            print(f"程序退出，退出码: {exit_code}")
            input("按回车键退出...")
            sys.exit(exit_code)

# 全局错误处理器实例
error_handler = PackagedErrorHandler()

def setup_global_error_handling():
    """设置全局错误处理"""
    # 设置未捕获异常处理器
    sys.excepthook = error_handler.handle_exception
    
    # 设置导入错误处理器
    def import_error_handler(module_name):
        return error_handler.handle_import_error(module_name)
    
    # 重写__import__函数来捕获导入错误
    original_import = __builtins__.__import__
    
    def safe_import(name, *args, **kwargs):
        try:
            return original_import(name, *args, **kwargs)
        except ImportError as e:
            error_handler.handle_import_error(name)
            raise e
    
    __builtins__.__import__ = safe_import

def safe_print(*args, **kwargs):
    """安全的打印函数"""
    if hasattr(sys, '_MEIPASS'):
        # 打包后记录到日志
        try:
            message = ' '.join(str(arg) for arg in args)
            logging.info(message)
        except Exception:
            pass
    else:
        # 开发环境正常打印
        print(*args, **kwargs)

def safe_input(prompt=""):
    """安全的输入函数"""
    if hasattr(sys, '_MEIPASS'):
        # 打包后返回空字符串
        return ""
    else:
        # 开发环境正常输入
        return input(prompt)
