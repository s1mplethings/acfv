#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
subprocess工具模块 - 解决Windows下的编码问题
"""

import subprocess
import sys
import logging


def safe_subprocess_run(*args, **kwargs):
    """
    安全的subprocess运行函数，自动处理Windows编码问题
    
    这个函数会自动为text=True的调用添加正确的编码设置，
    避免Windows系统上的GBK编码错误
    """
    
    # 如果设置了text=True，确保有正确的编码设置
    if kwargs.get('text', False):
        kwargs.setdefault('encoding', 'utf-8')
        kwargs.setdefault('errors', 'ignore')
    
    try:
        return subprocess.run(*args, **kwargs)
    except UnicodeDecodeError as e:
        logging.warning(f"Unicode解码错误，尝试使用备用编码: {e}")
        
        # 如果仍有编码问题，尝试使用bytes模式
        if 'text' in kwargs:
            kwargs.pop('text')
        if 'encoding' in kwargs:
            kwargs.pop('encoding')
        if 'errors' in kwargs:
            kwargs.pop('errors')
            
        result = subprocess.run(*args, **kwargs)
        
        # 手动解码输出
        if hasattr(result, 'stdout') and result.stdout:
            try:
                result.stdout = result.stdout.decode('utf-8', errors='ignore')
            except:
                result.stdout = result.stdout.decode('gbk', errors='ignore')
                
        if hasattr(result, 'stderr') and result.stderr:
            try:
                result.stderr = result.stderr.decode('utf-8', errors='ignore')
            except:
                result.stderr = result.stderr.decode('gbk', errors='ignore')
                
        return result


def safe_ffmpeg_run(cmd, **kwargs):
    """
    专门用于FFmpeg的安全subprocess运行函数
    
    Args:
        cmd: FFmpeg命令列表
        **kwargs: subprocess.run的其他参数
    """
    
    # FFmpeg的默认设置
    default_kwargs = {
        'capture_output': True,
        'text': True,
        'encoding': 'utf-8',
        'errors': 'ignore'
    }
    
    # 合并用户提供的参数
    default_kwargs.update(kwargs)
    
    try:
        return subprocess.run(cmd, **default_kwargs)
    except Exception as e:
        logging.error(f"FFmpeg命令执行失败: {' '.join(cmd)}")
        logging.error(f"错误: {e}")
        raise


def safe_ffprobe_run(video_path, probe_args=None, timeout=30):
    """
    专门用于FFprobe的安全运行函数
    
    Args:
        video_path: 视频文件路径
        probe_args: 额外的probe参数
        timeout: 超时时间
        
    Returns:
        subprocess运行结果
    """
    
    cmd = ['ffprobe', '-v', 'quiet']
    
    if probe_args:
        cmd.extend(probe_args)
    else:
        cmd.extend(['-print_format', 'json', '-show_format', '-show_streams'])
    
    cmd.append(video_path)
    
    return safe_subprocess_run(cmd, capture_output=True, text=True, timeout=timeout)


# 向后兼容的函数别名
subprocess_run_safe = safe_subprocess_run
