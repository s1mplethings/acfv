#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
处理模块包初始化文件
"""

__version__ = "2.0.0"
__author__ = "Interest Rating System"

# 不在这里导入所有模块，避免循环导入
# 只在需要时动态导入

__all__ = [
    "analyze_data",
    "clip_video",
    "extract_chat",
    "generate_ratings_json",
    "local_video_manager",
    "speaker_diarization_module",
    "speaker_separation_integration",
    "subtitle_generator",
    "transcribe_audio",
    "twitch_downloader",
    "video_emotion",
    "video_emotion_infer"
]
