"""Step 4: Speaker diarization using pyannote.audio"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import List
from .schemas import VADSegment, DiarizationSegment

logger = logging.getLogger(__name__)


def run_diarization(vocals_wav: Path, vad_segments: List[VADSegment]) -> List[DiarizationSegment]:
    """
    使用pyannote.audio进行说话人分离

    Args:
        vocals_wav: 人声音频
        vad_segments: VAD段用于强制对齐

    Returns:
        说话人分离段列表
    """
    logger.info(f"Running diarization on {vocals_wav}")
    
    try:
        # TODO: 实际实现pyannote调用
        # from pyannote.audio import Pipeline
        # pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization")
        # ...
        logger.warning("pyannote diarization not implemented yet, using fallback")
        return _fallback_single_speaker(vad_segments)
        
    except Exception as e:
        logger.error(f"Diarization failed: {e}, using fallback")
        return _fallback_single_speaker(vad_segments)


def _fallback_single_speaker(vad_segments: List[VADSegment]) -> List[DiarizationSegment]:
    """
    降级策略：生成单个speaker覆盖所有VAD区间

    Args:
        vad_segments: VAD段

    Returns:
        单speaker的diarization段
    """
    logger.warning("Using fallback: single speaker for all VAD segments")
    return [
        DiarizationSegment(start=seg.start, end=seg.end, speaker_id="spk_0")
        for seg in vad_segments
    ]


def align_diarization_to_vad(
    diarization: List[DiarizationSegment],
    vad_segments: List[VADSegment]
) -> List[DiarizationSegment]:
    """
    将diarization结果对齐到VAD区间（取交集）

    Args:
        diarization: 原始diarization结果
        vad_segments: VAD段

    Returns:
        对齐后的diarization段
    """
    aligned = []
    
    for dia_seg in diarization:
        for vad_seg in vad_segments:
            # 计算交集
            start = max(dia_seg.start, vad_seg.start)
            end = min(dia_seg.end, vad_seg.end)
            
            if start < end:  # 有交集
                aligned.append(DiarizationSegment(
                    start=start,
                    end=end,
                    speaker_id=dia_seg.speaker_id
                ))
    
    return sorted(aligned, key=lambda s: s.start)
