#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全的回调包装器
确保所有按钮点击都有异常处理，避免程序崩溃
"""

import sys
import traceback
from functools import wraps
from modules.gui_logger import gui_logger, log_error, log_exception

def safe_callback(func):
    """安全的回调装饰器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            # 记录按钮点击
            button_name = getattr(func, '__name__', '未知按钮')
            gui_logger.info(f"按钮点击: {button_name}")
            
            # 执行回调函数
            result = func(*args, **kwargs)
            
            # 记录成功
            gui_logger.info(f"按钮操作成功: {button_name}")
            return result
            
        except Exception as e:
            # 记录错误
            error_msg = f"按钮 {button_name} 执行失败: {str(e)}"
            log_exception(e, f"按钮回调错误: {button_name}")
            
            # 在打包后的环境中，不显示错误对话框
            if hasattr(sys, '_MEIPASS'):
                # 静默处理错误，只记录到日志
                pass
            else:
                # 开发环境显示错误
                print(f"❌ {error_msg}")
                traceback.print_exc()
            
            # 返回None表示操作失败
            return None
    
    return wrapper

def safe_operation(operation_name):
    """安全操作装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                gui_logger.info(f"开始操作: {operation_name}")
                
                # 执行操作
                result = func(*args, **kwargs)
                
                gui_logger.info(f"操作完成: {operation_name}")
                return result
                
            except Exception as e:
                error_msg = f"操作 {operation_name} 失败: {str(e)}"
                log_exception(e, f"操作失败: {operation_name}")
                
                if hasattr(sys, '_MEIPASS'):
                    # 打包后静默处理
                    pass
                else:
                    print(f"❌ {error_msg}")
                    traceback.print_exc()
                
                return None
        
        return wrapper
    return decorator

class SafeButtonHandler:
    """安全的按钮处理器"""
    
    def __init__(self):
        self.logger = gui_logger
    
    def handle_click(self, button_name, callback, *args, **kwargs):
        """处理按钮点击"""
        try:
            self.logger.info(f"处理按钮点击: {button_name}")
            result = callback(*args, **kwargs)
            self.logger.info(f"按钮 {button_name} 处理完成")
            return result
            
        except Exception as e:
            self.logger.error(f"按钮 {button_name} 处理失败: {e}")
            if not hasattr(sys, '_MEIPASS'):
                print(f"按钮 {button_name} 处理失败: {e}")
            return None
    
    def create_safe_callback(self, callback, button_name):
        """创建安全的回调函数"""
        def safe_callback_wrapper(*args, **kwargs):
            return self.handle_click(button_name, callback, *args, **kwargs)
        return safe_callback_wrapper

# 全局安全处理器实例
safe_handler = SafeButtonHandler()

# 便捷函数
def create_safe_button_callback(callback, button_name):
    """创建安全的按钮回调"""
    return safe_handler.create_safe_callback(callback, button_name)

def wrap_button_callback(callback):
    """包装按钮回调为安全版本"""
    return safe_callback(callback)

if __name__ == "__main__":
    print("🛡️ 安全回调模块")
    print("提供安全的GUI回调处理功能")
