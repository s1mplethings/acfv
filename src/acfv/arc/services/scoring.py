"""Scoring service extracting interest scoring utilities from analyze_data.

Provides:
 - compute_chat_density(chat_data, start, end)
 - vader_interest_score(text)
 - compute_relative_interest_score(all_scores, score)
 - score_segment(chat_density, sentiment_score, video_emotion, weights)
"""
from __future__ import annotations
from typing import List, Dict, Any
import math

def compute_chat_density(chat_data: List[Dict[str, Any]], start: float, end: float) -> float:
    if not chat_data:
        return 0.0
    count = 0
    for msg in chat_data:
        ts = msg.get('timestamp', 0)
        if start <= ts < end:
            count += 1
    duration = max(0.1, end - start)
    return min(1.0, count / (duration * 2.0))  # heuristic normalization

def vader_interest_score(text: str) -> float:
    if not text:
        return 0.0
    import re
    words = re.findall(r"\w+", text.lower())
    if not words:
        return 0.0
    # crude heuristic: emotional keywords boost
    emotional = sum(1 for w in words if w in {"great","wow","amazing","funny","wtf","nice","lol"})
    intensity = min(1.0, len(words) / 40.0)
    interest_score = (intensity * 0.7) + (min(1.0, emotional / 5.0) * 0.3)
    return min(max(interest_score, 0.0), 1.0)

def compute_relative_interest_score(all_scores: List[float], score: float) -> float:
    if not all_scores:
        return score
    import statistics
    mean = statistics.mean(all_scores)
    stdev = statistics.pstdev(all_scores) or 1e-6
    z = (score - mean) / stdev
    # squash z to 0..1 via sigmoid
    import math as _m
    return 1 / (1 + _m.exp(-z))

def score_segment(chat_density: float, sentiment_score: float, video_emotion: float, weights: Dict[str, float]) -> float:
    return (
        weights.get('CHAT_DENSITY_WEIGHT', 0.3) * chat_density +
        weights.get('CHAT_SENTIMENT_WEIGHT', 0.4) * sentiment_score +
        weights.get('VIDEO_EMOTION_WEIGHT', 0.3) * video_emotion
    )

__all__ = [
    'compute_chat_density','vader_interest_score','compute_relative_interest_score','score_segment'
]
