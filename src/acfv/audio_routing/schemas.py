"""Data schemas for audio routing module"""
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field


class VADSegment(BaseModel):
    """语音活动检测段"""
    start: float = Field(..., description="开始时间（秒）")
    end: float = Field(..., description="结束时间（秒）")


class DiarizationSegment(BaseModel):
    """说话人分离段"""
    start: float
    end: float
    speaker_id: str = Field(..., description="说话人ID（spk_0/spk_1...）")


class SpeakerProfile(BaseModel):
    """说话人角色映射"""
    role: str = Field(..., description="角色标签：streamer/tts/game_speech")
    score: float = Field(..., ge=0, le=1, description="匹配相似度分数")


class WordTimestamp(BaseModel):
    """词级时间戳"""
    w: str = Field(..., description="词")
    s: float = Field(..., description="开始时间")
    e: float = Field(..., description="结束时间")


class LabeledSegment(BaseModel):
    """带标签的转录段（最终输出）"""
    start: float
    end: float
    speaker_id: str
    role: str = Field(..., description="角色：streamer/tts/game_speech")
    text: str = Field(..., description="转录文本")
    words: Optional[List[WordTimestamp]] = Field(default=None, description="词级时间戳")


class GameNonSpeechSegment(BaseModel):
    """游戏非语音段（bgm/sfx）"""
    start: float
    end: float
    rms_db: float = Field(..., description="音量dB值")


class AudioRoutingConfig(BaseModel):
    """音频分流配置"""
    use_demucs: bool = Field(default=True, description="是否启用Demucs人声分离")
    
    class VADConfig(BaseModel):
        min_speech_sec: float = Field(default=0.25, description="最小语音段长度（秒）")
        merge_gap_sec: float = Field(default=0.20, description="合并间隔阈值（秒）")
    
    class DiarizationConfig(BaseModel):
        enabled: bool = Field(default=True, description="是否启用说话人分离")
    
    class RoleMappingConfig(BaseModel):
        thr_streamer: float = Field(default=0.75, description="主播相似度阈值")
        thr_tts: float = Field(default=0.75, description="TTS相似度阈值")
        thr_game: float = Field(default=0.72, description="游戏角色相似度阈值")
        default_role: str = Field(default="game_speech", description="默认角色")
    
    class ASRConfig(BaseModel):
        max_asr_sec: float = Field(default=20.0, description="最大转录段长度（秒）")
        language: str = Field(default="auto", description="语言代码或auto")
    
    class GameNonSpeechConfig(BaseModel):
        thr_game_bgm_db: float = Field(default=-28.0, description="bgm检测阈值（dB）")
        min_bgm_sec: float = Field(default=0.40, description="最小bgm段长度（秒）")
        merge_gap_bgm_sec: float = Field(default=0.20, description="bgm合并间隔（秒）")
    
    vad: VADConfig = Field(default_factory=VADConfig)
    diarization: DiarizationConfig = Field(default_factory=DiarizationConfig)
    role_mapping: RoleMappingConfig = Field(default_factory=RoleMappingConfig)
    asr: ASRConfig = Field(default_factory=ASRConfig)
    game_non_speech: GameNonSpeechConfig = Field(default_factory=GameNonSpeechConfig)
