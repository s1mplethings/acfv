#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
配置管理模块
用于安全地读取配置文件中的敏感信息
"""

import os
import json
import logging
from pathlib import Path

def load_huggingface_token():
    """
    从配置文件中加载HuggingFace token
    
    Returns:
        str: HuggingFace token，如果无法读取则返回None
    """
    # 获取当前文件所在目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(current_dir, 'config.json')
    
    try:
        # 首先检查配置文件是否存在
        if not os.path.exists(config_path):
            logging.warning(f"配置文件不存在: {config_path}")
            logging.info("请复制 config.json.example 为 config.json 并填入您的 HuggingFace token")
            return None
        
        # 读取配置文件
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 获取token
        token = config.get('huggingface_token')
        if not token or token == 'your_huggingface_token_here':
            logging.warning("HuggingFace token 未配置或使用默认值")
            logging.info("请在 config.json 中设置正确的 huggingface_token")
            return None
        
        logging.info("✅ HuggingFace token 加载成功")
        return token
        
    except json.JSONDecodeError as e:
        logging.error(f"配置文件格式错误: {e}")
        return None
    except Exception as e:
        logging.error(f"读取配置文件失败: {e}")
        return None

def setup_huggingface_environment():
    """
    设置HuggingFace环境变量
    
    Returns:
        bool: 设置成功返回True，失败返回False
    """
    token = load_huggingface_token()
    if not token:
        return False
    
    # 设置各种可能的环境变量名
    os.environ['HUGGINGFACE_HUB_TOKEN'] = token
    os.environ['HUGGING_FACE_HUB_TOKEN'] = token
    os.environ['HF_TOKEN'] = token
    
    logging.info("✅ HuggingFace 环境变量设置完成")
    return True

if __name__ == "__main__":
    # 测试配置加载
    print("🔧 测试配置加载...")
    token = load_huggingface_token()
    if token:
        print(f"✅ Token 加载成功: {token[:10]}...")
        setup_success = setup_huggingface_environment()
        if setup_success:
            print("✅ 环境变量设置成功")
        else:
            print("❌ 环境变量设置失败")
    else:
        print("❌ Token 加载失败")