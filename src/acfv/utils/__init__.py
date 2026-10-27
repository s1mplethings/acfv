# Utils package

import hashlib
import re
import unicodedata

__all__ = ["safe_slug", "extract_time_from_clip_filename"]


def safe_slug(text: str, max_length: int = 80) -> str:
    """Return a filesystem-safe slug with an optional length cap."""
    normalized = unicodedata.normalize("NFKC", text or "")
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", normalized)
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_-")
    if not cleaned:
        cleaned = "video"
    if len(cleaned) <= max_length:
        return cleaned
    digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:6]
    keep = max(10, max_length - len(digest) - 1)
    return f"{cleaned[:keep].rstrip('_-')}_{digest}"


def extract_time_from_clip_filename(filename: str):
    """
    从切片文件名提取时间信息，默认按 clip_<start>_<end>.mp4 结构解析。
    Returns (start_time, end_time) in seconds; falls back to (0, 0) on failure.
    """
    start_time = 0.0
    end_time = 0.0
    try:
        if filename and filename.startswith("clip_"):
            parts = filename.replace(".mp4", "").split("_")
            if len(parts) >= 3:
                start_time = float(parts[1])
                end_time = float(parts[2])
    except Exception:
        pass
    return start_time, end_time
