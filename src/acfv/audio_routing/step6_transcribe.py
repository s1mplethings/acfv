"""Step 6: Transcription using WhisperX"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import List
from .schemas import DiarizationSegment, LabeledSegment, SpeakerProfile

logger = logging.getLogger(__name__)


def transcribe_segments(
    diarization: List[DiarizationSegment],
    speaker_profiles: dict[str, SpeakerProfile],
    vocals_wav: Path,
    max_asr_sec: float = 20.0,
    language: str = "auto"
) -> List[LabeledSegment]:
    """
    使用WhisperX转录语音段

    Args:
        diarization: 说话人分离结果
        speaker_profiles: 说话人角色映射
        vocals_wav: 人声音频
        max_asr_sec: 最大转录段长度
        language: 语言代码

    Returns:
        带标签的转录段列表
    """
    logger.info(f"Transcribing {len(diarization)} segments")
    
    labeled_segments = []
    
    for seg in diarization:
        # 获取角色
        profile = speaker_profiles.get(seg.speaker_id)
        role = profile.role if profile else "game_speech"
        
        # TODO: 实际实现WhisperX调用
        # import whisperx
        # model = whisperx.load_model(...)
        # result = model.transcribe(audio_segment)
        
        # Placeholder: 空转录
        labeled_segments.append(LabeledSegment(
            start=seg.start,
            end=seg.end,
            speaker_id=seg.speaker_id,
            role=role,
            text="",  # TODO: 实际转录文本
            words=None
        ))
    
    logger.warning("WhisperX not implemented yet, returning empty transcriptions")
    return labeled_segments


def split_long_segments(segments: List[DiarizationSegment], max_duration: float) -> List[DiarizationSegment]:
    """
    切分过长的段以避免ASR卡住

    Args:
        segments: 原始段
        max_duration: 最大时长

    Returns:
        切分后的段
    """
    split = []
    
    for seg in segments:
        duration = seg.end - seg.start
        
        if duration <= max_duration:
            split.append(seg)
        else:
            # 简单切分：按max_duration均分
            num_splits = int(duration / max_duration) + 1
            split_dur = duration / num_splits
            
            for i in range(num_splits):
                split.append(DiarizationSegment(
                    start=seg.start + i * split_dur,
                    end=seg.start + (i + 1) * split_dur,
                    speaker_id=seg.speaker_id
                ))
    
    return split
