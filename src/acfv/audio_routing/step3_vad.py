"""Step 3: Voice Activity Detection using Silero VAD"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import List
from .schemas import VADSegment

logger = logging.getLogger(__name__)


def run_vad(vocals_wav: Path, min_speech_sec: float = 0.25, merge_gap_sec: float = 0.20) -> List[VADSegment]:
    """
    使用Silero VAD检测语音区间

    Args:
        vocals_wav: 人声音频
        min_speech_sec: 最小语音段长度
        merge_gap_sec: 合并间隔阈值

    Returns:
        VAD段列表
    """
    logger.info(f"Running VAD on {vocals_wav}")
    
    try:
        # TODO: 实际实现Silero VAD调用
        # 这里需要导入silero-vad并调用
        logger.warning("Silero VAD not implemented yet, returning empty")
        return []
        
    except Exception as e:
        logger.error(f"VAD failed: {e}")
        return []


def merge_vad_segments(segments: List[VADSegment], merge_gap: float, min_duration: float) -> List[VADSegment]:
    """
    合并和清洗VAD段

    Args:
        segments: 原始VAD段
        merge_gap: 合并间隔
        min_duration: 最小时长

    Returns:
        合并后的段
    """
    if not segments:
        return []
    
    # 按时间排序
    segments = sorted(segments, key=lambda s: s.start)
    
    merged = []
    current = segments[0]
    
    for next_seg in segments[1:]:
        # 如果间隔小于阈值，合并
        if next_seg.start - current.end <= merge_gap:
            current = VADSegment(start=current.start, end=next_seg.end)
        else:
            # 检查时长
            if current.end - current.start >= min_duration:
                merged.append(current)
            current = next_seg
    
    # 添加最后一段
    if current.end - current.start >= min_duration:
        merged.append(current)
    
    return merged
