from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

from ..storage.db import get_user_pref, save_user_pref
from ..storage.models import Clip, UserPreference

POSITIVE_FEEDBACK = {"like", "full_watch", "rewatch"}
NEGATIVE_FEEDBACK = {"dislike", "skip"}


def _default_pref(user_id: str) -> UserPreference:
    return UserPreference(user_id=user_id, tag_weights={}, feature_prefs={})


def _update_tag_weights(tag_weights: Dict[str, float], tags: Iterable[str], delta: float) -> Dict[str, float]:
    updated = dict(tag_weights)
    for tag in tags:
        updated[tag] = max(-3.0, min(3.0, updated.get(tag, 0.0) + delta))
    return updated


def update_user_preferences_from_interaction(db_path, user_id: str, clip: Clip, feedback_type: str, watch_ratio: float | None) -> UserPreference:
    pref = get_user_pref(db_path, user_id) or _default_pref(user_id)
    delta = 0.0
    if feedback_type in POSITIVE_FEEDBACK:
        delta = 0.3
    elif feedback_type in NEGATIVE_FEEDBACK:
        delta = -0.3
    elif watch_ratio is not None:
        delta = (watch_ratio - 0.5) * 0.4
    if delta != 0.0:
        pref.tag_weights = _update_tag_weights(pref.tag_weights, clip.tags, delta)
        pref.raw_preference_text = pref.raw_preference_text or ""
        save_user_pref(db_path, pref)
    return pref


def score_clip_for_user(pref: UserPreference | None, clip: Clip, base_sim_score: float = 0.0) -> float:
    if pref is None:
        return base_sim_score

    tag_score = 0.0
    for tag in clip.tags:
        tag_score += pref.tag_weights.get(tag, 0.0)

    feature_score = 0.0
    fp = pref.feature_prefs or {}
    if fp.get("min_duration") and clip.duration < fp["min_duration"]:
        feature_score -= 0.5
    if fp.get("max_duration") and clip.duration > fp["max_duration"]:
        feature_score -= 0.5
    if fp.get("min_emotion") and clip.emotion_score is not None:
        if clip.emotion_score < fp["min_emotion"]:
            feature_score -= 0.3
    if fp.get("min_talk_ratio") and clip.talk_ratio is not None:
        if clip.talk_ratio < fp["min_talk_ratio"]:
            feature_score -= 0.3

    highlight_bonus = clip.highlight_score or 0.0

    return float(base_sim_score + tag_score + feature_score + 0.1 * highlight_bonus)


def rerank_clips_for_user(
    pref: UserPreference | None,
    clips: List[Clip],
    base_scores: List[float],
) -> Tuple[List[Clip], List[float]]:
    scored = []
    for clip, base in zip(clips, base_scores):
        scored.append((score_clip_for_user(pref, clip, base), clip))
    scored.sort(key=lambda x: x[0], reverse=True)
    sorted_clips = [c for _, c in scored]
    sorted_scores = [s for s, _ in scored]
    return sorted_clips, sorted_scores
