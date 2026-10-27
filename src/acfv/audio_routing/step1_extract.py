"""Step 1: Audio extraction using FFmpeg"""
from __future__ import annotations
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_audio(input_video: Path, output_wav: Path) -> bool:
    """
    从视频提取音频为16kHz mono WAV

    Args:
        input_video: 输入视频路径
        output_wav: 输出WAV路径

    Returns:
        成功返回True，失败返回False
    """
    logger.info(f"Extracting audio from {input_video} to {output_wav}")
    
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        'ffmpeg', '-y',
        '-i', str(input_video),
        '-vn',  # 无视频
        '-acodec', 'pcm_s16le',  # 16-bit PCM
        '-ar', '16000',  # 16kHz
        '-ac', '1',  # mono
        str(output_wav)
    ]
    
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            text=True
        )
        logger.info(f"Audio extraction successful: {output_wav}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Audio extraction failed: {e.stderr}")
        return False
    except FileNotFoundError:
        logger.error("FFmpeg not found. Please install FFmpeg.")
        return False
