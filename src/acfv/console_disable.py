#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
控制台完全禁用模块
在打包后彻底禁用所有控制台相关功能
"""

import os
import sys
import io

class NullDevice:
    """空设备，完全忽略所有输入输出"""
    
    def __init__(self):
        pass
    
    def write(self, text):
        pass
    
    def read(self, size=-1):
        return ""
    
    def readline(self, size=-1):
        return ""
    
    def readlines(self, size=-1):
        return []
    
    def writelines(self, lines):
        pass
    
    def flush(self):
        pass
    
    def close(self):
        pass
    
    def fileno(self):
        return -1
    
    def isatty(self):
        return False
    
    def readable(self):
        return False
    
    def writable(self):
        return False
    
    def seekable(self):
        return False
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

def disable_console_completely():
    """完全禁用控制台"""
    if hasattr(sys, '_MEIPASS'):  # 只在打包后的环境中执行
        try:
            # 创建空设备
            null_device = NullDevice()
            
            # 重定向所有标准流
            sys.stdout = null_device
            sys.stderr = null_device
            sys.stdin = null_device
            
            # 重定向内置函数
            import builtins
            
            # 禁用print函数
            def null_print(*args, **kwargs):
                pass
            builtins.print = null_print
            
            # 禁用input函数
            def null_input(prompt=""):
                return ""
            builtins.input = null_input
            
            # 禁用help函数
            def null_help(*args, **kwargs):
                pass
            builtins.help = null_help
            
            # 设置环境变量禁用控制台
            os.environ['PYTHONUNBUFFERED'] = '0'
            os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
            
            # 尝试禁用Windows控制台
            try:
                if sys.platform.startswith('win'):
                    import ctypes
                    # 获取kernel32句柄
                    kernel32 = ctypes.windll.kernel32
                    # 获取当前进程句柄
                    process = kernel32.GetCurrentProcess()
                    # 设置进程控制台标志
                    kernel32.SetConsoleMode(process, 0)
            except Exception:
                pass
                
        except Exception:
            pass

# 在模块导入时立即执行
disable_console_completely()
