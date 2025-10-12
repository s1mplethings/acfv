#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模块包初始化文件
"""

__version__ = "2.0.0"
__author__ = "Interest Rating System"

# 不在这里导入所有模块，避免循环导入
# 只在需要时动态导入

__all__ = [
    "beautiful_progress_widget", 
    "clip_processing_tracker",
    "clips_manager",
    "gui_logger",
    "new_clips_manager",
    "pipeline_backend",
    "progress_manager",
    "progress_widget",
    "smart_progress_predictor",
    "ui_components"
]
