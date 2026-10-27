from __future__ import annotations

import contextlib
import math
import os
import wave
from pathlib import Path
from typing import Optional

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore

try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:  # pragma: no cover
    librosa = None  # type: ignore
    LIBROSA_AVAILABLE = False

try:
    import soundfile as sf
    SOUNDFILE_AVAILABLE = True
except ImportError:  # pragma: no cover
    sf = None  # type: ignore
    SOUNDFILE_AVAILABLE = False

from acfv.main_logging import log_debug, log_error, log_info, log_warning

# Feature extraction parameters mirror UltraFastExtractor for consistency.
HOP_LENGTH = 512
FRAME_LENGTH = 1024
N_FFT = 1024

DEFAULT_MUSIC_THRESHOLD = 0.9
DEFAULT_SILENCE_DB_THRESHOLD = -55.0
DEFAULT_MIN_MUTED_DURATION = 0.5  # seconds


def _apply_min_duration(mask: "np.ndarray", min_frames: int) -> "np.ndarray":
    if min_frames <= 1:
        return mask
    cleaned = mask.copy()
    run_start = None
    for idx, value in enumerate(mask):
        if value and run_start is None:
            run_start = idx
        elif not value and run_start is not None:
            if idx - run_start < min_frames:
                cleaned[run_start:idx] = False
            run_start = None
    if run_start is not None and len(mask) - run_start < min_frames:
        cleaned[run_start:] = False
    return cleaned


def _expand_neighbors(mask: "np.ndarray") -> "np.ndarray":
    if mask.size == 0:
        return mask
    expanded = mask.copy()
    expanded[:-1] |= mask[1:]
    expanded[1:] |= mask[:-1]
    return expanded


def _write_pcm16(output_path: Path, audio: "np.ndarray", sample_rate: int) -> None:
    data = np.clip(audio, -1.0, 1.0)
    pcm16 = (data * 32767.0).round().astype("<i2")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(wave.open(str(output_path), "wb")) as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())


def sanitize_audio_for_transcription(
    audio_path: str | os.PathLike[str],
    *,
    output_path: Optional[str | os.PathLike[str]] = None,
    music_threshold: Optional[float] = None,
    silence_db_threshold: float = DEFAULT_SILENCE_DB_THRESHOLD,
    min_muted_duration: float = DEFAULT_MIN_MUTED_DURATION,
) -> str:
    """
    Zero-out pure music and silent regions while preserving the original timeline.

    Returns the path of the audio file that should be used for transcription.
    """
    if np is None or not LIBROSA_AVAILABLE:
        log_debug("[音频预处理] 所需依赖缺失，跳过音频预处理")
        return str(audio_path)

    src_path = Path(audio_path)
    if not src_path.exists():
        log_error(f"[音频预处理] 音频文件不存在: {src_path}")
        return str(src_path)

    dst_path = Path(output_path) if output_path else src_path.with_name(
        f"{src_path.stem}_preprocessed{src_path.suffix or '.wav'}"
    )

    music_threshold = float(music_threshold or DEFAULT_MUSIC_THRESHOLD)
    music_threshold = max(0.0, min(1.0, music_threshold))

    try:
        src_stat = src_path.stat()
        if dst_path.exists():
            dst_stat = dst_path.stat()
            if dst_stat.st_mtime >= src_stat.st_mtime and dst_stat.st_size > 0:
                log_debug(f"[音频预处理] 复用已有预处理文件: {dst_path}")
                return str(dst_path)
    except OSError:
        pass

    try:
        audio, sr = librosa.load(str(src_path), sr=None, mono=True)
    except Exception as exc:  # pragma: no cover
        log_error(f"[音频预处理] 无法加载音频: {exc}")
        return str(src_path)

    if audio.size == 0:
        log_warning("[音频预处理] 音频内容为空，跳过预处理")
        return str(src_path)

    frame_duration = HOP_LENGTH / sr
    min_frames = max(1, int(math.ceil(min_muted_duration / frame_duration))) if min_muted_duration > 0 else 1

    try:
        stft = librosa.stft(audio, n_fft=N_FFT, hop_length=HOP_LENGTH)
        magnitude = np.abs(stft)
        spectral_flatness = librosa.feature.spectral_flatness(S=magnitude)[0]
        zero_cross = librosa.feature.zero_crossing_rate(
            audio, frame_length=FRAME_LENGTH, hop_length=HOP_LENGTH
        )[0]
        rms = librosa.feature.rms(y=audio, frame_length=FRAME_LENGTH, hop_length=HOP_LENGTH)[0]
    except Exception as exc:  # pragma: no cover
        log_error(f"[音频预处理] 特征提取失败: {exc}")
        return str(src_path)

    frame_count = min(len(spectral_flatness), len(zero_cross), len(rms))
    if frame_count == 0:
        log_warning("[音频预处理] 未提取到有效帧，跳过预处理")
        return str(src_path)

    spectral_flatness = spectral_flatness[:frame_count]
    zero_cross = zero_cross[:frame_count]
    rms = rms[:frame_count]

    music_prob = 0.6 * spectral_flatness + 0.4 * (1.0 - zero_cross)
    music_prob = np.clip(music_prob, 0.0, 1.0)
    rms_db = 20.0 * np.log10(np.maximum(rms, 1e-6))

    music_mask = music_prob >= music_threshold
    silence_mask = rms_db <= silence_db_threshold
    combined_mask = _expand_neighbors(np.logical_or(music_mask, silence_mask))
    combined_mask = _apply_min_duration(combined_mask, min_frames)

    if not combined_mask.any():
        log_info("[音频预处理] 未检测到纯音乐或静音片段，跳过预处理")
        return str(src_path)

    sample_mask = np.zeros_like(audio, dtype=bool)
    for frame_idx, flagged in enumerate(combined_mask):
        if not flagged:
            continue
        start = frame_idx * HOP_LENGTH
        end = min(len(audio), start + FRAME_LENGTH)
        sample_mask[start:end] = True

    muted_samples = int(sample_mask.sum())
    muted_ratio = muted_samples / len(audio)
    log_info(
        f"[音频预处理] 将 {muted_ratio * 100:.1f}% 的音频置零 (music≥{music_threshold:.2f} 或 "
        f"rms≤{silence_db_threshold:.1f}dB)"
    )

    if muted_ratio > 0.98:
        log_warning("[音频预处理] 静音比例过高，疑似阈值配置异常，改用原始音频")
        return str(src_path)

    processed = audio.copy()
    processed[sample_mask] = 0.0
    processed = processed.astype(np.float32, copy=False)

    try:
        if SOUNDFILE_AVAILABLE:
            sf.write(str(dst_path), processed, sr, subtype="PCM_16")
        else:
            _write_pcm16(dst_path, processed, sr)
    except Exception as exc:  # pragma: no cover
        log_error(f"[音频预处理] 写入预处理音频失败: {exc}")
        return str(src_path)

    log_info(f"[音频预处理] 预处理音频已保存: {dst_path}")
    return str(dst_path)


__all__ = ["sanitize_audio_for_transcription"]
