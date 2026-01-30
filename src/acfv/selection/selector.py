from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .contract_selection import select_candidates


def select_clips(score_dict: Dict[str, Any], settings) -> List[Tuple[float, float]]:
    """Legacy wrapper that returns (start, end) tuples using contract-based selection."""
    segments = []
    t = score_dict.get("t") or []
    s = score_dict.get("score") or []
    for ts, score in zip(t, s):
        segments.append({"start": float(ts), "end": float(ts), "text": "", "score": float(score)})

    payload = {
        "segments": segments,
        "strategy": "topk",
        "topk": getattr(getattr(settings, "selection", None), "topk", 10) if settings else 10,
        "min_duration": 0.0,
        "merge_overlap": False,
    }
    result = select_candidates(payload)
    return [(seg["start"], seg["end"]) for seg in result.get("candidates", [])]
