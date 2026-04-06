"""Step 7: Game non-speech (bgm/sfx) detection"""
from __future__ import annotations
import logging
import numpy as np
from pathlib import Path
from typing import List
from .schemas import VADSegment, GameNonSpeechSegment

logger = logging.getLogger(__name__)


def detect_game_non_speech(
    no_vocals_wav: Path,
    vad_segments: List[VADSegment],
    thr_bgm_db: float = -28.0,
    min_bgm_sec: float = 0.40,
    merge_gap_sec: float = 0.20
) -> List[GameNonSpeechSegment]:
    """
    检测游戏非语音段（bgm/sfx）

    Args:
        no_vocals_wav: 非人声音频
        vad_segments: VAD段（用于排除）
        thr_bgm_db: bgm检测阈值（dB）
        min_bgm_sec: 最小bgm段长度
        merge_gap_sec: 合并间隔

    Returns:
        游戏非语音段列表
    """
    logger.info(f"Detecting game non-speech from {no_vocals_wav}")
    
    try:
        # TODO: 实际实现RMS计算
        # import librosa
        # y, sr = librosa.load(no_vocals_wav, sr=16000)
        # rms = librosa.feature.rms(y=y, hop_length=800)[0]  # 50ms hop
        # ...
        
        logger.warning("Game non-speech detection not implemented yet, returning empty")
        return []
        
    except Exception as e:
        logger.error(f"Game non-speech detection failed: {e}")
        return []


def _calculate_rms_db(audio_data: np.ndarray, hop_samples: int) -> tuple[np.ndarray, np.ndarray]:
    """
    计算短时RMS并转换为dB

    Args:
        audio_data: 音频数据
        hop_samples: 跳跃采样数

    Returns:
        (time_array, rms_db_array)
    """
    # TODO: 实现RMS计算
    return np.array([]), np.array([])


def _exclude_vad_from_candidates(
    candidates: List[GameNonSpeechSegment],
    vad_segments: List[VADSegment]
) -> List[GameNonSpeechSegment]:
    """
    从候选区间中排除VAD段

    Args:
        candidates: 候选bgm段
        vad_segments: VAD段

    Returns:
        排除后的bgm段
    """
    filtered = []
    
    for cand in candidates:
        # 检查是否与任何VAD段重叠
        overlaps = any(
            not (cand.end <= vad.start or cand.start >= vad.end)
            for vad in vad_segments
        )
        
        if not overlaps:
            filtered.append(cand)
    
    return filtered


def _merge_bgm_segments(
    segments: List[GameNonSpeechSegment],
    merge_gap: float,
    min_duration: float
) -> List[GameNonSpeechSegment]:
    """
    合并bgm段碎片

    Args:
        segments: 原始段
        merge_gap: 合并间隔
        min_duration: 最小时长

    Returns:
        合并后的段
    """
    if not segments:
        return []
    
    segments = sorted(segments, key=lambda s: s.start)
    merged = []
    current = segments[0]
    
    for next_seg in segments[1:]:
        if next_seg.start - current.end <= merge_gap:
            # 合并，取平均rms_db
            avg_rms = (current.rms_db + next_seg.rms_db) / 2
            current = GameNonSpeechSegment(
                start=current.start,
                end=next_seg.end,
                rms_db=avg_rms
            )
        else:
            if current.end - current.start >= min_duration:
                merged.append(current)
            current = next_seg
    
    if current.end - current.start >= min_duration:
        merged.append(current)
    
    return merged
