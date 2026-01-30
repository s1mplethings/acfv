from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

SCHEMA_VERSION = "1.0.0"


@dataclass
class MergeConfig:
    merge_gap_sec: float = 1.0
    max_merged_duration: float = 120.0


def _normalize_segments(items: Any) -> List[Dict[str, Any]]:
    segments: List[Dict[str, Any]] = []
    if not isinstance(items, list):
        return segments
    for idx, seg in enumerate(items):
        if not isinstance(seg, dict):
            continue
        try:
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", 0.0))
        except Exception:
            continue
        if end <= start:
            raise ValueError(f"invalid segment at index {idx}: start >= end")
        segments.append(
            {
                "start": start,
                "end": end,
                "text": (seg.get("text") or "").strip(),
                "score": float(seg.get("score", 0.0) or 0.0),
                "features": seg.get("features") or {},
                "_idx": idx,
            }
        )
    return segments


def _validate_config(payload: Dict[str, Any]) -> MergeConfig:
    gap = float(payload.get("merge_gap_sec", 1.0) or 0.0)
    max_dur = float(payload.get("max_merged_duration", 120.0) or 0.0)
    if gap < 0:
        raise ValueError("merge_gap_sec must be >= 0")
    if max_dur <= 0:
        raise ValueError("max_merged_duration must be > 0")
    return MergeConfig(merge_gap_sec=gap, max_merged_duration=max_dur)


def merge_segments(payload: Dict[str, Any]) -> Dict[str, Any]:
    segments = _normalize_segments(payload.get("segments") or [])
    cfg = _validate_config(payload)
    if not segments:
        return {
            "schema_version": SCHEMA_VERSION,
            "merged_segments": [],
            "merge_gap_sec": cfg.merge_gap_sec,
            "max_merged_duration": cfg.max_merged_duration,
        }

    segments.sort(key=lambda s: (s["start"], s["end"]))
    merged: List[Dict[str, Any]] = []
    current = None

    for seg in segments:
        if current is None:
            current = dict(seg)
            current["merged_from"] = [seg["_idx"]]
            continue

        gap = seg["start"] - current["end"]
        merged_duration = seg["end"] - current["start"]
        if gap <= cfg.merge_gap_sec and merged_duration <= cfg.max_merged_duration:
            current["end"] = max(current["end"], seg["end"])
            current["text"] = (current.get("text") or "") + " " + (seg.get("text") or "")
            current["score"] = max(current.get("score", 0.0), seg.get("score", 0.0))
            current["merged_from"].append(seg["_idx"])
        else:
            merged.append(current)
            current = dict(seg)
            current["merged_from"] = [seg["_idx"]]

    if current is not None:
        merged.append(current)

    for seg in merged:
        seg.pop("_idx", None)
        seg["start"] = round(seg["start"], 3)
        seg["end"] = round(seg["end"], 3)
        seg["score"] = round(float(seg.get("score", 0.0)), 3)

    merged.sort(key=lambda s: (s["start"], s["end"]))

    return {
        "schema_version": SCHEMA_VERSION,
        "merged_segments": merged,
        "merge_gap_sec": cfg.merge_gap_sec,
        "max_merged_duration": cfg.max_merged_duration,
    }


__all__ = ["merge_segments", "MergeConfig", "SCHEMA_VERSION"]
