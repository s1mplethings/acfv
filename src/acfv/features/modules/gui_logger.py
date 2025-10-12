#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI专用日志系统
替换所有print语句，避免控制台输出
"""

import os
import sys
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler

class GUILogger:
    """GUI专用日志器"""
    
    def __init__(self, name="InterestRating", log_dir="logs"):
        self.name = name
        self.log_dir = log_dir
        self.setup_logging()
    
    def setup_logging(self):
        """设置日志系统"""
        try:
            # 创建日志目录
            if hasattr(sys, '_MEIPASS'):
                # 打包后的环境，日志放在exe同目录
                exe_dir = os.path.dirname(sys.executable)
                log_path = os.path.join(exe_dir, self.log_dir)
            else:
                # 开发环境，日志放在当前目录
                log_path = os.path.join(os.getcwd(), self.log_dir)
            
            os.makedirs(log_path, exist_ok=True)
            
            # 创建日志文件
            log_file = os.path.join(log_path, f"{self.name}.log")
            
            # 配置日志格式
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            
            # 创建文件处理器（带轮转）
            file_handler = RotatingFileHandler(
                log_file, 
                maxBytes=10*1024*1024,  # 10MB
                backupCount=5,
                encoding='utf-8'
            )
            file_handler.setFormatter(formatter)
            file_handler.setLevel(logging.INFO)
            
            # 创建根日志器
            self.logger = logging.getLogger(self.name)
            self.logger.setLevel(logging.INFO)
            self.logger.addHandler(file_handler)
            
            # 清除其他处理器
            self.logger.propagate = False
            
        except Exception as e:
            # 如果日志设置失败，创建基本的日志器
            self.logger = logging.getLogger(self.name)
            self.logger.addHandler(logging.NullHandler())
    
    def info(self, message):
        """信息日志"""
        self.logger.info(message)
    
    def warning(self, message):
        """警告日志"""
        self.logger.warning(message)
    
    def error(self, message):
        """错误日志"""
        self.logger.error(message)
    
    def debug(self, message):
        """调试日志"""
        self.logger.debug(message)
    
    def critical(self, message):
        """严重错误日志"""
        self.logger.critical(message)
    
    def exception(self, message):
        """异常日志（包含堆栈跟踪）"""
        self.logger.exception(message)

# 全局日志器实例
gui_logger = GUILogger()

# 替换print函数的函数
def gui_print(*args, **kwargs):
    """GUI版本的print，输出到日志文件而不是控制台"""
    message = ' '.join(str(arg) for arg in args)
    gui_logger.info(message)

# 安全的输入函数
def gui_input(prompt=""):
    """GUI版本的input，在打包后返回空字符串"""
    if hasattr(sys, '_MEIPASS'):
        gui_logger.info(f"INPUT请求: {prompt}")
        return ""
    else:
        return input(prompt)

# 错误记录函数
def log_error(error, context=""):
    """记录错误到日志文件"""
    if context:
        gui_logger.error(f"{context}: {error}")
    else:
        gui_logger.error(f"错误: {error}")

# 异常记录函数
def log_exception(exception, context=""):
    """记录异常到日志文件"""
    if context:
        gui_logger.exception(f"{context}: {exception}")
    else:
        gui_logger.exception(f"异常: {exception}")

# 按钮点击日志
def log_button_click(button_name, action=""):
    """记录按钮点击事件"""
    if action:
        gui_logger.info(f"按钮点击: {button_name} - {action}")
    else:
        gui_logger.info(f"按钮点击: {button_name}")

# 操作完成日志
def log_operation_complete(operation, result=""):
    """记录操作完成"""
    if result:
        gui_logger.info(f"操作完成: {operation} - {result}")
    else:
        gui_logger.info(f"操作完成: {operation}")

# 替换内置函数（在打包后的环境中）
def replace_builtins():
    """替换内置函数"""
    if hasattr(sys, '_MEIPASS'):
        import builtins
        builtins.print = gui_print
        builtins.input = gui_input
        builtins.help = lambda *args, **kwargs: None
