from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "max_split_size_mb:128")

try:
    import whisper

    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

try:
    import torch

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

from acfv.main_logging import log_debug, log_error, log_info, log_warning
from acfv.runtime.storage import processing_path

SCHEMA_VERSION = "1.0.0"
DEFAULT_SAMPLE_RATE = 16000
ALLOWED_MODEL_SIZES = {"tiny", "base", "small", "medium", "large-v2"}
ALLOWED_OUTPUT_FORMATS = {"json", "srt", "ass", "all"}


def _ensure_extended_path(path: str | os.PathLike) -> str:
    """Add Windows long-path prefix when needed to avoid ffmpeg failures."""
    as_str = str(path)
    if os.name == "nt":
        normalized = os.path.normpath(as_str)
        if not normalized.startswith("\\\\?\\") and len(normalized) >= 240:
            return "\\\\?\\" + normalized
        return normalized
    return as_str


def check_ffmpeg_availability() -> bool:
    """Return True when ffmpeg is callable."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def get_audio_info_ffprobe(audio_path: str | os.PathLike) -> Optional[Dict[str, Any]]:
    """Inspect audio/video file with ffprobe."""
    try:
        target = _ensure_extended_path(audio_path)
        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            target,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=30,
        )
        if result.returncode != 0:
            return None

        info = json.loads(result.stdout)
        audio_stream = None
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "audio":
                audio_stream = stream
                break

        duration = float(info["format"].get("duration", 0))
        sample_rate = int(audio_stream.get("sample_rate", DEFAULT_SAMPLE_RATE)) if audio_stream else DEFAULT_SAMPLE_RATE
        channels = int(audio_stream.get("channels", 1)) if audio_stream else 1

        return {
            "duration": duration,
            "sample_rate": sample_rate,
            "channels": channels,
            "format": info["format"].get("format_name", "unknown"),
        }
    except Exception as exc:
        log_error(f"[ffprobe] failed: {exc}")
        return None


def extract_audio_segment_ffmpeg(audio_path: str | os.PathLike, start_time: float, end_time: float, output_path: str | os.PathLike) -> bool:
    """Extract an audio slice with ffmpeg."""
    try:
        duration = max(0.0, end_time - start_time)
        if duration <= 0:
            return False

        input_path = _ensure_extended_path(audio_path)
        output_target = _ensure_extended_path(output_path)
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-ss",
            str(start_time),
            "-i",
            input_path,
            "-t",
            str(duration),
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(DEFAULT_SAMPLE_RATE),
            "-ac",
            "1",
            "-f",
            "wav",
            output_target,
        ]
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=300,
            check=True,
        )
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except subprocess.TimeoutExpired:
        log_error(f"[ffmpeg] timed out while slicing {start_time}-{end_time}")
        return False
    except subprocess.CalledProcessError as exc:
        log_error(f"[ffmpeg] failed to slice audio: {exc.stderr or exc}")
        return False
    except Exception as exc:
        log_error(f"[ffmpeg] unexpected error while slicing: {exc}")
        return False


def extract_audio_segment_safe(audio_path: str | os.PathLike, start_time: float, end_time: float, output_path: str | os.PathLike) -> bool:
    """Safe wrapper that extracts an audio slice or logs the failure."""
    if not check_ffmpeg_availability():
        log_error("ffmpeg is required for audio slicing")
        return False
    return extract_audio_segment_ffmpeg(audio_path, start_time, end_time, output_path)


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(content)
    tmp.replace(path)


def _format_srt_timestamp(seconds: float) -> str:
    total_ms = int(round(max(0.0, seconds) * 1000))
    hours, remainder = divmod(total_ms, 3600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _format_ass_timestamp(seconds: float) -> str:
    total_cs = int(round(max(0.0, seconds) * 100))
    hours, remainder = divmod(total_cs, 360_000)
    minutes, remainder = divmod(remainder, 6000)
    secs, centis = divmod(remainder, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _write_srt(segments: List[Dict[str, Any]], path: Path) -> None:
    lines: List[str] = []
    for idx, seg in enumerate(segments, 1):
        start = _format_srt_timestamp(seg["start"])
        end = _format_srt_timestamp(seg["end"])
        lines.append(str(idx))
        lines.append(f"{start} --> {end}")
        lines.append(seg["text"])
        lines.append("")
    _atomic_write_text(path, "\n".join(lines))


def _write_ass(segments: List[Dict[str, Any]], path: Path) -> None:
    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "Collisions: Normal",
        "Timer: 100.0000",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,Arial,28,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,"
        "2,2,10,10,10,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    body: List[str] = []
    for seg in segments:
        start = _format_ass_timestamp(seg["start"])
        end = _format_ass_timestamp(seg["end"])
        text = seg["text"].replace("\n", "\\N")
        body.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    _atomic_write_text(path, "\n".join(header + body))


def _confidence_from_segment(seg: Dict[str, Any]) -> Optional[float]:
    avg_logprob = seg.get("avg_logprob")
    if avg_logprob is not None:
        try:
            prob = 1.0 / (1.0 + math.exp(-float(avg_logprob)))
            return max(0.0, min(1.0, prob))
        except Exception:
            pass
    no_speech_prob = seg.get("no_speech_prob")
    if no_speech_prob is not None:
        try:
            prob = 1.0 - float(no_speech_prob)
            return max(0.0, min(1.0, prob))
        except Exception:
            pass
    return None


def _normalize_segment(seg: Dict[str, Any], offset: float = 0.0, speaker: Optional[str] = None) -> Optional[Dict[str, Any]]:
    try:
        start = round(float(seg.get("start", 0.0)) + offset, 3)
        end = round(float(seg.get("end", 0.0)) + offset, 3)
        if end <= start:
            return None
    except Exception:
        return None

    text = (seg.get("text") or "").strip()
    if not text:
        return None

    confidence = _confidence_from_segment(seg)
    segment = {
        "start": start,
        "end": end,
        "text": text,
        "confidence": round(confidence, 3) if confidence is not None else 0.0,
        "speaker": speaker or seg.get("speaker") or "unk",
    }
    return segment


def _should_use_fp16(model_device: str) -> bool:
    if not TORCH_AVAILABLE:
        return False
    if not torch.cuda.is_available():
        return False
    return model_device.startswith("cuda")


def _load_whisper_model(model_size: str, device: Optional[str]) -> whisper.Whisper:
    desired_device = device or ("cuda" if TORCH_AVAILABLE and torch.cuda.is_available() else "cpu")
    log_info(f"[transcribe] loading whisper model {model_size} on {desired_device}")
    try:
        return whisper.load_model(model_size, device=desired_device)
    except Exception as exc:
        log_warning(f"[transcribe] model load failed on {desired_device}: {exc}")
        if desired_device.startswith("cuda"):
            try:
                return whisper.load_model(model_size, device="cpu")
            except Exception as exc_cpu:
                log_warning(f"[transcribe] fallback to CPU failed: {exc_cpu}")
        if model_size != "tiny":
            log_info("[transcribe] retrying with tiny model on CPU")
            return whisper.load_model("tiny", device="cpu")
        raise


def _transcribe_file(
    whisper_model: Any,
    audio_path: Path,
    language: Optional[str],
    prompt: Optional[str],
    offset: float,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    if not WHISPER_AVAILABLE:
        raise RuntimeError("whisper is not installed")

    try:
        model_device = str(getattr(whisper_model, "device", "cpu"))
    except Exception:
        model_device = "cpu"

    fp16 = _should_use_fp16(model_device)
    language_arg = None
    if language and language.lower() not in {"auto", "default", "detect"}:
        language_arg = language

    log_debug(f"[transcribe] running whisper on {audio_path} (offset={offset})")
    result = whisper_model.transcribe(
        str(audio_path),
        language=language_arg,
        initial_prompt=prompt or "",
        word_timestamps=False,
        fp16=fp16,
    )
    detected_lang = result.get("language")
    segments: List[Dict[str, Any]] = []
    for seg in result.get("segments", []):
        normalized = _normalize_segment(seg, offset=offset)
        if normalized:
            segments.append(normalized)
    return segments, detected_lang


def _transcribe_with_splitting(
    whisper_model: Any,
    audio_path: Path,
    duration: float,
    language: Optional[str],
    prompt: Optional[str],
    split_duration: Optional[int],
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    if not split_duration or split_duration <= 0 or duration <= split_duration:
        return _transcribe_file(whisper_model, audio_path, language, prompt, offset=0.0)

    work_dir = audio_path.parent
    collected: List[Dict[str, Any]] = []
    detected_language: Optional[str] = None
    start_time = 0.0
    idx = 0
    try:
        while start_time < duration:
            end_time = min(start_time + split_duration, duration)
            chunk_path = work_dir / f"chunk_{idx}.wav"
            if not extract_audio_segment_safe(audio_path, start_time, end_time, chunk_path):
                log_error(f"[transcribe] failed to extract chunk {start_time}-{end_time}")
                start_time = end_time
                idx += 1
                continue
            segs, lang = _transcribe_file(whisper_model, chunk_path, language, prompt, offset=start_time)
            if lang and not detected_language:
                detected_language = lang
            collected.extend(segs)
            start_time = end_time
            idx += 1
    finally:
        for file in work_dir.glob("chunk_*.wav"):
            try:
                file.unlink(missing_ok=True)
            except Exception:
                pass

    collected.sort(key=lambda item: (item["start"], item["end"]))
    return collected, detected_language


def _write_outputs(
    transcript_path: Path,
    srt_path: Optional[Path],
    ass_path: Optional[Path],
    payload: Dict[str, Any],
    segments: List[Dict[str, Any]],
) -> None:
    _atomic_write_json(transcript_path, payload)
    if srt_path:
        _write_srt(segments, srt_path)
    if ass_path:
        _write_ass(segments, ass_path)


def _validate_language(lang: Optional[str]) -> Optional[str]:
    if not lang:
        return None
    if not isinstance(lang, str):
        raise ValueError("language must be a string")
    text = lang.strip().lower()
    if len(text) != 2 or not text.isalpha():
        raise ValueError(f"invalid language code: {lang}")
    return text


@dataclass
class TranscribeOptions:
    source_path: Path
    work_dir: Path
    language: Optional[str]
    model_size: str
    device: Optional[str]
    split_duration: Optional[int]
    diarization: bool
    prompt: Optional[str]
    output_format: str
    transcript_path_override: Optional[Path] = None


def _parse_payload(payload: Dict[str, Any], transcript_path_override: Optional[str] = None) -> TranscribeOptions:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")

    if "source_path" not in payload:
        raise ValueError("source_path is required")
    source_path = Path(str(payload["source_path"])).expanduser()
    if not source_path.is_file():
        raise FileNotFoundError(f"source_path not found: {source_path}")
    if os.name == "nt" and len(str(source_path)) >= 240:
        log_warning(f"[transcribe] long path detected, enabling long-path prefix: {source_path}")
        source_path = Path(_ensure_extended_path(source_path))

    work_dir_value = payload.get("work_dir") or processing_path("working")
    work_dir = Path(str(work_dir_value))
    work_dir.mkdir(parents=True, exist_ok=True)

    language = _validate_language(payload.get("language"))

    model_size = str(payload.get("model_size", "base")).lower()
    if model_size not in ALLOWED_MODEL_SIZES:
        raise ValueError(f"model_size must be one of {sorted(ALLOWED_MODEL_SIZES)}")

    device = payload.get("device")
    if device:
        device = str(device).lower()
        if device not in {"cpu", "cuda"}:
            raise ValueError("device must be cpu or cuda")

    split_duration = payload.get("split_duration")
    if split_duration is not None:
        try:
            split_duration = int(split_duration)
        except Exception:
            raise ValueError("split_duration must be an integer")
        if split_duration <= 0:
            raise ValueError("split_duration must be > 0")

    diarization = bool(payload.get("diarization", False))

    prompt = payload.get("prompt")
    if prompt is not None:
        prompt = str(prompt)

    output_format = str(payload.get("output_format", "json")).lower()
    if output_format not in ALLOWED_OUTPUT_FORMATS:
        raise ValueError(f"output_format must be one of {sorted(ALLOWED_OUTPUT_FORMATS)}")

    override_path = Path(transcript_path_override) if transcript_path_override else None
    return TranscribeOptions(
        source_path=source_path,
        work_dir=work_dir,
        language=language,
        model_size=model_size,
        device=device,
        split_duration=split_duration,
        diarization=diarization,
        prompt=prompt,
        output_format=output_format,
        transcript_path_override=override_path,
    )


def _prepare_audio(options: TranscribeOptions) -> Tuple[Path, Dict[str, Any]]:
    if not check_ffmpeg_availability():
        raise RuntimeError("ffmpeg is required for transcription")

    info = get_audio_info_ffprobe(options.source_path)
    if not info:
        raise RuntimeError(f"unable to probe audio stream for {options.source_path}")

    canonical = options.work_dir / f"{options.source_path.stem}_canonical.wav"
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        _ensure_extended_path(options.source_path),
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(DEFAULT_SAMPLE_RATE),
        "-ac",
        "1",
        _ensure_extended_path(canonical),
    ]
    log_info(f"[transcribe] normalizing audio -> {canonical}")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=600,
    )
    if result.returncode != 0 or not canonical.exists():
        raise RuntimeError(f"ffmpeg normalization failed: {result.stderr}")

    normalized_info = get_audio_info_ffprobe(canonical)
    if not normalized_info:
        normalized_info = info
    return canonical, normalized_info


def transcribe_audio(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Transcribe audio according to the contract."""
    options = _parse_payload(payload, transcript_path_override=payload.get("transcript_path"))
    canonical_audio, audio_info = _prepare_audio(options)
    duration = float(audio_info.get("duration") or 0.0)

    transcript_path = options.transcript_path_override or options.work_dir / f"{options.source_path.stem}.transcript.json"
    srt_path: Optional[Path] = None
    ass_path: Optional[Path] = None
    if options.output_format in {"srt", "all"}:
        srt_path = transcript_path.with_suffix(".srt")
    if options.output_format in {"ass", "all"}:
        ass_path = transcript_path.with_suffix(".ass")

    if duration < 1.0:
        log_warning(f"[transcribe] empty or too short audio ({duration:.2f}s), returning empty segments")
        empty_payload = {
            "schema_version": SCHEMA_VERSION,
            "transcript_path": str(transcript_path),
            "language": options.language or "und",
            "duration_sec": round(duration, 3),
            "segments": [],
        }
        _write_outputs(transcript_path, srt_path, ass_path, empty_payload, [])
        return empty_payload

    whisper_model = _load_whisper_model(options.model_size, options.device)
    segments, detected_language = _transcribe_with_splitting(
        whisper_model,
        canonical_audio,
        duration,
        options.language,
        options.prompt,
        options.split_duration,
    )
    segments.sort(key=lambda seg: (seg["start"], seg["end"]))

    if options.diarization:
        log_warning("[transcribe] diarization requested but not implemented; keeping speaker='unk'")

    language_out = options.language or detected_language or "und"
    avg_conf = None
    if segments:
        confidences = [seg.get("confidence") for seg in segments if seg.get("confidence") is not None]
        if confidences:
            avg_conf = round(sum(confidences) / len(confidences), 3)

    output_payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "transcript_path": str(transcript_path),
        "language": language_out,
        "duration_sec": round(duration, 3),
        "segments": segments,
    }
    if avg_conf is not None:
        output_payload["avg_confidence"] = avg_conf
    if srt_path:
        output_payload["srt_path"] = str(srt_path)
    if ass_path:
        output_payload["ass_path"] = str(ass_path)

    _write_outputs(transcript_path, srt_path, ass_path, output_payload, segments)
    return output_payload


def transcribe_audio_segment_safe(audio_path: str, start_time: float, end_time: float, whisper_model: Any) -> List[Dict[str, Any]]:
    """Backward-compatible helper that returns normalized segments."""
    temp_dir = None
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix="whisper_seg_"))
        temp_audio = temp_dir / "segment.wav"
        if not extract_audio_segment_safe(audio_path, start_time, end_time, temp_audio):
            return []
        segments, _ = _transcribe_file(whisper_model, temp_audio, language=None, prompt=None, offset=start_time)
        return segments
    except Exception as exc:
        log_error(f"[transcribe] segment failed {start_time}-{end_time}: {exc}")
        return []
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


def process_audio_segments(
    audio_path: str,
    output_file: Optional[str] = None,
    segment_length: int = 300,
    whisper_model_name: str = "base",
    host_transcription_file: Optional[str] = None,
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """Legacy entry that maps to the contract-based transcribe_audio."""
    payload: Dict[str, Any] = {
        "source_path": audio_path,
        "model_size": kwargs.get("model_size", whisper_model_name),
        "language": kwargs.get("language"),
        "device": kwargs.get("device"),
        "split_duration": kwargs.get("split_duration", segment_length),
        "prompt": kwargs.get("prompt"),
        "diarization": kwargs.get("diarization", False),
        "output_format": kwargs.get("output_format", "json"),
    }

    if kwargs.get("work_dir"):
        payload["work_dir"] = kwargs["work_dir"]
    if output_file:
        payload["transcript_path"] = output_file

    result = transcribe_audio(payload)
    segments = result.get("segments", [])

    if host_transcription_file:
        host_segments = [dict(seg, speaker="host", is_host=True) for seg in segments]
        try:
            _atomic_write_json(Path(host_transcription_file), host_segments)
        except Exception as exc:
            log_error(f"[transcribe] failed to write host transcription: {exc}")

    return segments


def install_dependencies() -> bool:
    """Placeholder kept for backward compatibility."""
    missing = []
    if not check_ffmpeg_availability():
        missing.append("ffmpeg")
    if not WHISPER_AVAILABLE:
        missing.append("whisper (pip install openai-whisper)")
    if missing:
        log_info("missing dependencies: " + ", ".join(missing))
        return False
    return True


if __name__ == "__main__":
    import sys

    if not install_dependencies():
        print("请安装缺少的依赖后重试")
        sys.exit(1)

    if len(sys.argv) < 2:
        print("用法: python transcribe_audio.py <音频文件路径> [输出文件路径]")
        sys.exit(1)

    audio_path = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else str(processing_path("transcription.json"))

    try:
        transcribe_audio({"source_path": audio_path, "transcript_path": output_file})
        print("转录完成！")
    except Exception as exc:
        print(f"转录失败: {exc}")
        sys.exit(1)

