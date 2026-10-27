"""Step 2: Stem separation using Demucs"""
from __future__ import annotations
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def separate_stems(audio_wav: Path, output_dir: Path, use_demucs: bool = True) -> tuple[Path, Path]:
    """
    使用Demucs分离人声和伴奏

    Args:
        audio_wav: 输入音频
        output_dir: 输出目录
        use_demucs: 是否启用Demucs

    Returns:
        (vocals_path, no_vocals_path) 元组
    """
    vocals_path = output_dir / "vocals.wav"
    no_vocals_path = output_dir / "no_vocals.wav"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if not use_demucs:
        logger.info("Demucs disabled, using original audio as vocals")
        import shutil
        shutil.copy(audio_wav, vocals_path)
        shutil.copy(audio_wav, no_vocals_path)
        return vocals_path, no_vocals_path
    
    try:
        # TODO: 实际实现Demucs调用
        # 这里需要导入demucs库并调用
        logger.warning("Demucs not implemented yet, falling back to copy")
        import shutil
        shutil.copy(audio_wav, vocals_path)
        shutil.copy(audio_wav, no_vocals_path)
        return vocals_path, no_vocals_path
        
    except Exception as e:
        logger.error(f"Demucs failed: {e}, falling back")
        import shutil
        shutil.copy(audio_wav, vocals_path)
        shutil.copy(audio_wav, no_vocals_path)
        return vocals_path, no_vocals_path
