"""Step 5: Speaker role mapping using Resemblyzer"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Dict, Optional
from .schemas import SpeakerProfile, DiarizationSegment

logger = logging.getLogger(__name__)


def map_speakers_to_roles(
    diarization: list[DiarizationSegment],
    vocals_wav: Path,
    refs_dir: Optional[Path],
    thr_streamer: float = 0.75,
    thr_tts: float = 0.75,
    thr_game: float = 0.72,
    default_role: str = "game_speech"
) -> Dict[str, SpeakerProfile]:
    """
    使用Resemblyzer将说话人映射到角色

    Args:
        diarization: 说话人分离结果
        vocals_wav: 人声音频
        refs_dir: 参考音频目录
        thr_streamer: 主播阈值
        thr_tts: TTS阈值
        thr_game: 游戏角色阈值
        default_role: 默认角色

    Returns:
        speaker_id -> SpeakerProfile 映射
    """
    logger.info("Mapping speakers to roles")
    
    # 加载参考embedding
    ref_embeddings = _load_reference_embeddings(refs_dir)
    
    if not ref_embeddings:
        logger.warning("No reference embeddings, using default role for all speakers")
        unique_speakers = set(seg.speaker_id for seg in diarization)
        return {
            spk_id: SpeakerProfile(role=default_role, score=0.0)
            for spk_id in unique_speakers
        }
    
    # TODO: 实际实现Resemblyzer调用
    # from resemblyzer import VoiceEncoder, preprocess_wav
    # encoder = VoiceEncoder()
    # ...
    
    logger.warning("Resemblyzer not implemented yet, using default mapping")
    unique_speakers = set(seg.speaker_id for seg in diarization)
    return {
        spk_id: SpeakerProfile(role=default_role, score=0.5)
        for spk_id in unique_speakers
    }


def _load_reference_embeddings(refs_dir: Optional[Path]) -> Dict[str, any]:
    """
    加载参考音频embedding

    Args:
        refs_dir: 参考音频目录

    Returns:
        role -> embedding 映射
    """
    if not refs_dir or not refs_dir.exists():
        return {}
    
    embeddings = {}
    
    # 检查参考文件
    for role in ["streamer", "tts", "game_speech"]:
        ref_file = refs_dir / f"{role}.wav"
        if ref_file.exists():
            logger.info(f"Found reference for {role}: {ref_file}")
            # TODO: 实际加载embedding
            embeddings[role] = None  # placeholder
        else:
            logger.warning(f"Missing reference for {role}")
    
    return embeddings
