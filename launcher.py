#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
程序启动器 - 专门用于打包后的启动
处理控制台输出重定向和错误处理
"""

import os
import sys
import traceback
import logging
from datetime import datetime

def setup_packaged_environment():
    """设置打包后的环境"""
    # 设置环境变量
    os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'
    os.environ['OMP_NUM_THREADS'] = '1'
    os.environ['PYTHONWARNINGS'] = 'ignore::FutureWarning,ignore::UserWarning'
    
    # 在打包后的环境中禁用控制台输出
    if hasattr(sys, '_MEIPASS'):
        # 重定向所有输出到日志文件
        log_dir = os.path.join(os.path.dirname(sys.executable), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        
        log_file = os.path.join(log_dir, f'startup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
        
        # 设置日志
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler(sys.stdout) if not hasattr(sys, '_MEIPASS') else logging.NullHandler()
            ]
        )
        
        # 重定向标准输出和错误到日志
        class LoggingStream:
            def __init__(self, level):
                self.level = level
                self.logger = logging.getLogger()
            
            def write(self, text):
                if text.strip():
                    self.logger.log(self.level, text.strip())
            
            def flush(self):
                pass
        
        if hasattr(sys, '_MEIPASS'):
            sys.stdout = LoggingStream(logging.INFO)
            sys.stderr = LoggingStream(logging.ERROR)

def main():
    """主启动函数"""
    try:
        # 设置打包后的环境
        setup_packaged_environment()
        
        # 设置全局错误处理
        try:
            from error_handler import setup_global_error_handling
            setup_global_error_handling()
        except ImportError:
            logging.warning("错误处理模块导入失败，使用默认错误处理")
        
        # 记录启动信息
        logging.info("程序启动器开始运行")
        logging.info(f"Python版本: {sys.version}")
        logging.info(f"工作目录: {os.getcwd()}")
        
        # 导入并运行主程序
        from main import main as main_program
        
        logging.info("主程序模块导入成功，开始执行")
        exit_code = main_program()
        
        logging.info(f"主程序执行完成，退出码: {exit_code}")
        return exit_code
        
    except ImportError as e:
        logging.error(f"模块导入失败: {e}")
        if hasattr(sys, '_MEIPASS'):
            # 打包后直接退出
            return 1
        else:
            # 开发环境显示错误
            print(f"模块导入失败: {e}")
            input("按回车键退出...")
            return 1
            
    except Exception as e:
        logging.error(f"启动器运行失败: {e}")
        logging.error(f"详细错误: {traceback.format_exc()}")
        
        if hasattr(sys, '_MEIPASS'):
            # 打包后直接退出
            return 1
        else:
            # 开发环境显示错误
            print(f"启动器运行失败: {e}")
            traceback.print_exc()
            input("按回车键退出...")
            return 1

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except Exception as e:
        # 最后的错误处理
        if hasattr(sys, '_MEIPASS'):
            # 打包后静默退出
            sys.exit(1)
        else:
            # 开发环境显示错误
            print(f"启动器致命错误: {e}")
            traceback.print_exc()
            input("按回车键退出...")
            sys.exit(1)
