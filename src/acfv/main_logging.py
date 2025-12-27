# main_logging.py

import logging
from datetime import datetime

from acfv.runtime.storage import logs_path

log_file = logs_path("processing.log")

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(str(log_file), encoding='utf-8', mode='a'),
        logging.StreamHandler()  # 同时输出到控制台
    ]
)

def log_debug(message):
    logging.debug(message)

def log_info(message):
    logging.info(message)

def log_error(message):
    logging.error(message)

def log_warning(message):
    logging.warning(message)

# 添加启动日志
log_info("=" * 60)
log_info("🚀 日志系统启动")
log_info(f"📅 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
log_info("=" * 60)
