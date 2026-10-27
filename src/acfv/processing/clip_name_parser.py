from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


def duration_from_clip_name(name: str) -> Optional[float]:
    stem = Path(name).stem
    match = re.search(r"_(\d+(?:\.\d+)?)s-(\d+(?:\.\d+)?)s$", stem)
    if match:
        start, end = float(match.group(1)), float(match.group(2))
        return end - start if end > start else None
    match = re.search(r"_(\d+)-(\d+)$", stem)
    if match:
        start_ms, end_ms = int(match.group(1)), int(match.group(2))
        return (end_ms - start_ms) / 1000.0 if end_ms > start_ms else None
    match = re.match(r"clip_\d+_(\d+(?:\.\d+)?)_(\d+(?:\.\d+)?)$", stem)
    if match:
        start, end = float(match.group(1)), float(match.group(2))
        return end - start if end > start else None
    return None
