from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "1.0.0"
ALLOWED_STRATEGIES = {"topk", "threshold"}


@dataclass
class SelectionConfig:
    strategy: str = "topk"
    topk: Optional[int] = 10
    min_score: Optional[float] = None
    min_duration: float = 0.0
    max_duration: Optional[float] = None
    merge_overlap: bool = True


def _validate_segments(segments: Any) -> List[Dict[str, Any]]:
    if not isinstance(segments, list):
        raise ValueError("segments must be a list")
    normalized = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        try:
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", 0.0))
        except Exception:
            continue
        if end <= start:
            continue
        record = {
            "start": round(start, 3),
            "end": round(end, 3),
            "text": (seg.get("text") or "").strip(),
            "score": float(seg.get("score", seg.get("interest_score", 0.0)) or 0.0),
            "features": seg.get("features") or {},
        }
        normalized.append(record)
    return normalized


def _validate_config(payload: Dict[str, Any]) -> SelectionConfig:
    strategy = str(payload.get("strategy", "topk")).lower()
    if strategy not in ALLOWED_STRATEGIES:
        raise ValueError("strategy must be one of topk|threshold")

    topk = payload.get("topk") if strategy == "topk" else None
    if topk is not None:
        topk = int(topk)
        if topk < 1:
            raise ValueError("topk must be > 0 when strategy=topk")

    min_score = payload.get("min_score") if strategy == "threshold" else None
    if min_score is not None:
        min_score = float(min_score)

    min_duration = float(payload.get("min_duration", 0.0) or 0.0)
    max_duration_val = payload.get("max_duration")
    max_duration = float(max_duration_val) if max_duration_val not in (None, "", False) else None
    if max_duration is not None and max_duration <= 0:
        raise ValueError("max_duration must be > 0 when provided")
    if max_duration is not None and min_duration > max_duration:
        raise ValueError("min_duration must be <= max_duration")

    merge_overlap = bool(payload.get("merge_overlap", True))

    return SelectionConfig(
        strategy=strategy,
        topk=topk,
        min_score=min_score,
        min_duration=min_duration,
        max_duration=max_duration,
        merge_overlap=merge_overlap,
    )


def _merge_overlaps(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not candidates:
        return []
    merged: List[Dict[str, Any]] = []
    for seg in sorted(candidates, key=lambda s: s["start"]):
        if not merged:
            merged.append(dict(seg))
            continue
        last = merged[-1]
        if seg["start"] <= last["end"]:
            last["end"] = max(last["end"], seg["end"])
            last["score"] = max(last["score"], seg["score"])
        else:
            merged.append(dict(seg))
    return merged


def _filter_duration(segs: List[Dict[str, Any]], cfg: SelectionConfig) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for seg in segs:
        dur = seg["end"] - seg["start"]
        if dur < max(cfg.min_duration, 0.0):
            continue
        if cfg.max_duration is not None and dur > cfg.max_duration:
            continue
        results.append(seg)
    return results


def select_candidates(payload: Dict[str, Any]) -> Dict[str, Any]:
    segments = _validate_segments(payload.get("segments") or [])
    cfg = _validate_config(payload)

    if not segments:
        return {
            "schema_version": SCHEMA_VERSION,
            "candidates": [],
            "strategy": cfg.strategy,
            "topk": cfg.topk,
            "min_score": cfg.min_score,
        }

    candidates = _filter_duration(segments, cfg)

    if cfg.strategy == "threshold" and cfg.min_score is not None:
        candidates = [seg for seg in candidates if seg["score"] >= cfg.min_score]
    elif cfg.strategy == "topk":
        candidates = sorted(candidates, key=lambda s: (s["score"], -s["start"]), reverse=True)
        if cfg.topk is not None:
            candidates = candidates[: cfg.topk]

    if cfg.merge_overlap:
        candidates = _merge_overlaps(candidates)

    # final sort: score desc, then start asc for determinism
    candidates = sorted(candidates, key=lambda s: (-s["score"], s["start"]))

    for seg in candidates:
        seg["start"] = round(seg["start"], 3)
        seg["end"] = round(seg["end"], 3)
        seg["score"] = round(float(seg.get("score", 0.0)), 3)

    return {
        "schema_version": SCHEMA_VERSION,
        "candidates": candidates,
        "strategy": cfg.strategy,
        "topk": cfg.topk,
        "min_score": cfg.min_score,
    }


__all__ = ["select_candidates", "SelectionConfig", "SCHEMA_VERSION"]
