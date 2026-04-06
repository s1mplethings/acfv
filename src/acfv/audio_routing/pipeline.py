"""Audio routing pipeline orchestrator"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Optional
import yaml

from .schemas import AudioRoutingConfig
from .step1_extract import extract_audio
from .step2_stems import separate_stems
from .step3_vad import run_vad, merge_vad_segments
from .step4_diarization import run_diarization, align_diarization_to_vad
from .step5_role_mapping import map_speakers_to_roles
from .step6_transcribe import transcribe_segments, split_long_segments
from .step7_game_non_speech import detect_game_non_speech

logger = logging.getLogger(__name__)


class AudioRoutingPipeline:
    """音频分流处理管道"""
    
    def __init__(self, config: AudioRoutingConfig, workdir: Path):
        self.config = config
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        
        # 设置日志
        self.log_file = self.workdir / "logs.txt"
        self._setup_logging()
    
    def _setup_logging(self):
        """配置日志输出"""
        file_handler = logging.FileHandler(self.log_file, mode='w', encoding='utf-8')
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        ))
        logging.getLogger('acfv.audio_routing').addHandler(file_handler)
    
    def run(
        self,
        input_video: Path,
        refs_dir: Optional[Path] = None
    ) -> bool:
        """
        运行完整的音频分流管道

        Args:
            input_video: 输入视频
            refs_dir: 参考音频目录

        Returns:
            成功返回True
        """
        logger.info(f"=== Starting audio routing pipeline ===")
        logger.info(f"Input: {input_video}")
        logger.info(f"Workdir: {self.workdir}")
        logger.info(f"Refs: {refs_dir}")
        
        try:
            # Step 1: 音频抽取
            audio_wav = self.workdir / "audio.wav"
            if not extract_audio(input_video, audio_wav):
                logger.error("Step 1 failed: Audio extraction")
                return False
            
            # Step 2: Stem分离
            stems_dir = self.workdir / "stems"
            vocals_wav, no_vocals_wav = separate_stems(
                audio_wav, stems_dir, self.config.use_demucs
            )
            
            # Step 3: VAD
            vad_segments = run_vad(
                vocals_wav,
                self.config.vad.min_speech_sec,
                self.config.vad.merge_gap_sec
            )
            vad_segments = merge_vad_segments(
                vad_segments,
                self.config.vad.merge_gap_sec,
                self.config.vad.min_speech_sec
            )
            self._save_json(vad_segments, "vad_speech.json")
            logger.info(f"VAD detected {len(vad_segments)} speech segments")
            
            # Step 4: Diarization
            diarization = run_diarization(vocals_wav, vad_segments)
            if self.config.diarization.enabled:
                diarization = align_diarization_to_vad(diarization, vad_segments)
            self._save_json(diarization, "diarization.json")
            logger.info(f"Diarization produced {len(diarization)} speaker segments")
            
            # Step 5: 角色映射
            speaker_profiles = map_speakers_to_roles(
                diarization,
                vocals_wav,
                refs_dir,
                self.config.role_mapping.thr_streamer,
                self.config.role_mapping.thr_tts,
                self.config.role_mapping.thr_game,
                self.config.role_mapping.default_role
            )
            self._save_json(speaker_profiles, "speaker_profiles.json")
            logger.info(f"Mapped {len(speaker_profiles)} speakers to roles")
            
            # Step 6: 转录
            diarization_split = split_long_segments(diarization, self.config.asr.max_asr_sec)
            labeled_segments = transcribe_segments(
                diarization_split,
                speaker_profiles,
                vocals_wav,
                self.config.asr.max_asr_sec,
                self.config.asr.language
            )
            self._save_json(labeled_segments, "labeled_segments.json")
            logger.info(f"Transcribed {len(labeled_segments)} segments")
            
            # Step 7: 游戏非语音检测
            game_non_speech = detect_game_non_speech(
                no_vocals_wav,
                vad_segments,
                self.config.game_non_speech.thr_game_bgm_db,
                self.config.game_non_speech.min_bgm_sec,
                self.config.game_non_speech.merge_gap_bgm_sec
            )
            self._save_json(game_non_speech, "game_non_speech.json")
            logger.info(f"Detected {len(game_non_speech)} game non-speech segments")
            
            logger.info("=== Audio routing pipeline completed successfully ===")
            return True
            
        except Exception as e:
            logger.error(f"Pipeline failed: {e}", exc_info=True)
            return False
    
    def _save_json(self, data, filename: str):
        """保存JSON数据"""
        output_path = self.workdir / filename
        
        # 转换Pydantic模型
        if hasattr(data, '__iter__') and not isinstance(data, (str, dict)):
            json_data = [
                item.model_dump() if hasattr(item, 'model_dump') else item
                for item in data
            ]
        elif hasattr(data, 'model_dump'):
            json_data = data.model_dump()
        elif isinstance(data, dict):
            json_data = {
                k: v.model_dump() if hasattr(v, 'model_dump') else v
                for k, v in data.items()
            }
        else:
            json_data = data
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        
        logger.debug(f"Saved {filename}")


def load_config(config_path: Path) -> AudioRoutingConfig:
    """
    加载配置文件

    Args:
        config_path: 配置文件路径

    Returns:
        配置对象
    """
    if not config_path.exists():
        logger.warning(f"Config not found: {config_path}, using defaults")
        return AudioRoutingConfig()
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config_dict = yaml.safe_load(f)
    
    return AudioRoutingConfig(**config_dict)
