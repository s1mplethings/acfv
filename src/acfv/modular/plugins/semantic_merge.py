from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from acfv import config as app_config
from acfv.modular.contracts import ART_SEGMENTS, ART_SEGMENTS_SEMANTIC, ART_TRANSCRIPT
from acfv.modular.types import ModuleContext, ModuleSpec

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
UNITS = "ms"
SORT_POLICY = "start_ms_asc_end_ms_asc"


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=True, indent=2)
    tmp.replace(path)


def _get_config_float(name: str, fallback: float) -> float:
    cm = getattr(app_config, "config_manager", None)
    try:
        if cm is None:
            return float(fallback)
        value = cm.get(name, fallback)
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _get_config_bool(name: str, fallback: bool) -> bool:
    cm = getattr(app_config, "config_manager", None)
    try:
        if cm is None:
            return bool(fallback)
        value = cm.get(name, fallback)
        return bool(value)
    except Exception:
        return bool(fallback)


def _count_meaningful_chars(text: str) -> int:
    if not text:
        return 0
    return len(re.findall(r"\w", text))


def _normalize_transcript(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        segments_raw = payload.get("segments", [])
    else:
        segments_raw = payload or []
    segments: List[Dict[str, Any]] = []
    for seg in segments_raw:
        if not isinstance(seg, dict):
            continue
        try:
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", 0.0))
        except Exception:
            continue
        text = (seg.get("text") or "").strip()
        if end <= start or not text:
            continue
        segments.append({"start": start, "end": end, "text": text})
    segments.sort(key=lambda s: s["start"])
    return segments


def _normalize_analysis_segments(payload: Any) -> List[Dict[str, Any]]:
    segments_raw = []
    units = "sec"
    if isinstance(payload, dict):
        segments_raw = payload.get("segments", [])
        units = str(payload.get("units") or "sec").lower()
    else:
        segments_raw = payload or []

    normalized: List[Dict[str, Any]] = []
    for seg in segments_raw:
        if not isinstance(seg, dict):
            continue
        try:
            if "start_ms" in seg or "end_ms" in seg:
                start = float(seg.get("start_ms", 0.0)) / (1000.0 if units in ("ms", "") else 1.0)
                end = float(seg.get("end_ms", 0.0)) / (1000.0 if units in ("ms", "") else 1.0)
            else:
                start = float(seg.get("start", 0.0))
                end = float(seg.get("end", 0.0))
        except Exception:
            continue
        if end <= start:
            continue
        score_val = seg.get("score", seg.get("interest_score", seg.get("rating", 0.0)))
        try:
            score = float(score_val or 0.0)
        except Exception:
            score = 0.0
        normalized.append({"start": start, "end": end, "score": score})
    return normalized


def _build_similarity_fn(texts: List[str]):
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        vectorizer = TfidfVectorizer(max_features=5000)
        mat = vectorizer.fit_transform(texts) if texts else None

        def cosine(i: int, j: int) -> float:
            if mat is None:
                return 1.0
            return float(cosine_similarity(mat[i], mat[j])[0][0])

        return cosine
    except Exception:
        import math
        import re
        from collections import Counter

        def to_bow(t: str) -> Counter:
            tokens = re.findall(r"\w+", (t or "").lower())
            return Counter(tokens)

        bows = [to_bow(text) for text in texts]

        def cosine(i: int, j: int) -> float:
            a, b = bows[i], bows[j]
            if not a or not b:
                return 0.0
            keys = set(a) | set(b)
            dot = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
            na = math.sqrt(sum(v * v for v in a.values()))
            nb = math.sqrt(sum(v * v for v in b.values()))
            return (dot / (na * nb)) if na > 0 and nb > 0 else 0.0

        return cosine


def _score_from_analysis(
    analysis_segments: List[Dict[str, Any]],
    start: float,
    end: float,
) -> tuple[Optional[float], int]:
    scores = []
    overlap_count = 0
    for seg in analysis_segments:
        s = seg.get("start", 0.0)
        e = seg.get("end", 0.0)
        overlap = max(0.0, min(end, e) - max(start, s))
        if overlap > 0:
            scores.append(float(seg.get("score", 0.0)))
            overlap_count += 1
    if scores:
        return sum(scores) / len(scores), overlap_count
    return None, overlap_count


def _segments_to_contract(
    segments_sec: List[Dict[str, Any]],
    target_sec: float,
    min_sec: float,
    max_sec: float,
    sim_threshold: float,
    max_gap: float,
) -> Dict[str, Any]:
    contract_segments: List[Dict[str, Any]] = []
    for rank, seg in enumerate(segments_sec, start=1):
        start_ms = int(round(seg["start"] * 1000))
        end_ms = int(round(seg["end"] * 1000))
        if end_ms <= start_ms:
            continue
        item = {
            "start_ms": start_ms,
            "end_ms": end_ms,
            "score": float(seg.get("score", 0.0)),
            "rank": rank,
        }
        if seg.get("score_base") is not None:
            item["score_base"] = float(seg.get("score_base"))
        if seg.get("score_scale") is not None:
            item["score_scale"] = float(seg.get("score_scale"))
        if seg.get("overlap_count") is not None:
            item["overlap_count"] = int(seg.get("overlap_count"))
        text_val = seg.get("text")
        if text_val:
            item["text"] = text_val
        contract_segments.append(item)

    return {
        "schema_version": SCHEMA_VERSION,
        "units": UNITS,
        "sort": SORT_POLICY,
        "policy": {
            "target_duration_ms": int(target_sec * 1000),
            "min_duration_ms": int(min_sec * 1000),
            "max_duration_ms": int(max_sec * 1000),
            "similarity_threshold": float(sim_threshold),
            "max_gap_ms": int(max_gap * 1000),
            "allow_overlap": False,
            "max_segments": len(contract_segments),
        },
        "segments": contract_segments,
    }


def run(ctx: ModuleContext) -> Dict[str, Any]:
    transcript_payload = ctx.inputs[ART_TRANSCRIPT].payload if ART_TRANSCRIPT in ctx.inputs else []
    analysis_payload = ctx.inputs[ART_SEGMENTS].payload if ART_SEGMENTS in ctx.inputs else []
    transcript_segments = _normalize_transcript(transcript_payload)
    analysis_segments = _normalize_analysis_segments(analysis_payload)

    use_semantic = _get_config_bool("SEMANTIC_SEGMENT_MODE", True)
    if not transcript_segments or not use_semantic:
        logger.info("[semantic_merge] fallback to analysis segments (semantic disabled or empty transcript)")
        segments = []
        for seg in analysis_segments:
            segments.append(
                {
                    "start": seg["start"],
                    "end": seg["end"],
                    "score": seg.get("score", 0.0),
                }
            )
        contract = _segments_to_contract(
            segments,
            target_sec=_get_config_float("SEMANTIC_TARGET_DURATION", 240.0),
            min_sec=_get_config_float("MIN_CLIP_DURATION", 60.0),
            max_sec=_get_config_float("MAX_CLIP_DURATION", 600.0),
            sim_threshold=_get_config_float("SEMANTIC_SIMILARITY_THRESHOLD", 0.75),
            max_gap=_get_config_float("SEMANTIC_MAX_TIME_GAP", 60.0),
        )
        work_dir = Path(ctx.store.run_dir) / "work"
        _write_json(work_dir / "segments_semantic.json", contract)
        return {ART_SEGMENTS_SEMANTIC: contract}

    target_sec = _get_config_float("SEMANTIC_TARGET_DURATION", 300.0)
    min_sec = _get_config_float("MIN_CLIP_DURATION", max(120.0, target_sec * 0.6))
    floor_min = _get_config_float("MIN_TARGET_CLIP_DURATION", 180.0)
    min_sec = max(min_sec, floor_min)
    min_sec = max(min_sec, 180.0)
    max_sec = _get_config_float("MAX_CLIP_DURATION", 600.0)
    max_sec = max(max_sec, min_sec)
    duration_weight = _get_config_float("SEMANTIC_DURATION_WEIGHT", 0.25)
    score_warn = _get_config_float("SEMANTIC_SCORE_WARN", 1000.0)
    sim_threshold = _get_config_float("SEMANTIC_SIMILARITY_THRESHOLD", 0.85)
    max_gap = _get_config_float("SEMANTIC_MAX_TIME_GAP", 60.0)
    stickiness_sec = _get_config_float("SEMANTIC_STICKINESS_SEC", 60.0)
    min_text_chars = int(_get_config_float("SEMANTIC_MIN_TEXT_CHARS", 20.0))
    min_text_per_sec = _get_config_float("SEMANTIC_MIN_TEXT_PER_SEC", 0.2)

    texts = [seg["text"] for seg in transcript_segments]
    cosine = _build_similarity_fn(texts)

    semantic_segments: List[Dict[str, Any]] = []
    cur_start = None
    cur_end = None
    cur_last_idx = None
    cur_texts: List[str] = []

    for idx, seg in enumerate(transcript_segments):
        s = seg["start"]
        e = seg["end"]
        if cur_start is None:
            cur_start, cur_end, cur_last_idx, cur_texts = s, e, idx, [seg["text"]]
            continue

        gap = s - cur_end
        try:
            similar = cosine(cur_last_idx, idx) >= sim_threshold if cur_last_idx is not None else True
        except Exception:
            similar = True

        new_dur = max(cur_end, e) - cur_start
        current_len = cur_end - cur_start
        if current_len < min_sec:
            cur_end = max(cur_end, e)
            cur_last_idx = idx
            cur_texts.append(seg["text"])
            continue

        allow_break_len = min_sec + max(0.0, stickiness_sec)
        if (gap > max_gap) or (new_dur >= max_sec) or ((current_len >= allow_break_len) and (not similar) and (current_len >= target_sec * 0.8)):
            semantic_segments.append({"start": cur_start, "end": cur_end, "text": " ".join(cur_texts)})
            cur_start, cur_end, cur_last_idx, cur_texts = s, e, idx, [seg["text"]]
        else:
            cur_end = max(cur_end, e)
            cur_last_idx = idx
            cur_texts.append(seg["text"])

    if cur_start is not None:
        semantic_segments.append({"start": cur_start, "end": cur_end, "text": " ".join(cur_texts)})

    filtered_segments: List[Dict[str, Any]] = []
    for seg in semantic_segments:
        duration_sec = max(seg["end"] - seg["start"], 0.001)
        text_val = seg.get("text") or ""
        meaningful_chars = _count_meaningful_chars(text_val)
        required_chars = max(float(min_text_chars), duration_sec * max(min_text_per_sec, 0.0))
        if meaningful_chars < required_chars:
            logger.info(
                "[semantic_merge] drop segment (low text) %.2fs-%.2fs dur=%.1fs chars=%d req=%.1f",
                seg["start"],
                seg["end"],
                duration_sec,
                meaningful_chars,
                required_chars,
            )
            continue
        filtered_segments.append(seg)

    if not filtered_segments and semantic_segments:
        logger.warning("[semantic_merge] all segments filtered by text length; keeping original segments")
        filtered_segments = semantic_segments

    for seg in filtered_segments:
        base_score, overlap_count = _score_from_analysis(analysis_segments, seg["start"], seg["end"])
        duration_sec = max(seg["end"] - seg["start"], 0.001)
        if base_score is None:
            base_score = duration_sec
        # 稍微偏向更长语义段，避免过短段占据高分
        scale = 1.0 + max(0.0, duration_weight) * (duration_sec / max(target_sec, 1.0))
        score = float(base_score) * scale
        seg["score"] = score
        seg["score_base"] = float(base_score)
        seg["score_scale"] = float(scale)
        seg["overlap_count"] = int(overlap_count)
        logger.info(
            "[semantic_merge] score seg=%.2fs-%.2fs dur=%.1fs base=%.3f scale=%.3f final=%.3f overlaps=%d",
            seg["start"],
            seg["end"],
            duration_sec,
            float(base_score),
            scale,
            score,
            overlap_count,
        )
        if score_warn > 0 and score >= score_warn:
            logger.warning(
                "[semantic_merge] high score=%.3f dur=%.1fs overlaps=%d base=%.3f",
                score,
                duration_sec,
                overlap_count,
                float(base_score),
            )

    logger.info("[semantic_merge] segments=%d target=%.1fs", len(filtered_segments), target_sec)

    contract = _segments_to_contract(
        filtered_segments,
        target_sec=target_sec,
        min_sec=min_sec,
        max_sec=max_sec,
        sim_threshold=sim_threshold,
        max_gap=max_gap,
    )

    work_dir = Path(ctx.store.run_dir) / "work"
    _write_json(work_dir / "segments_semantic.json", contract)
    return {ART_SEGMENTS_SEMANTIC: contract}


spec = ModuleSpec(
    name="semantic_merge",
    version="1",
    inputs=[ART_TRANSCRIPT, ART_SEGMENTS],
    outputs=[ART_SEGMENTS_SEMANTIC],
    run=run,
    description="Merge transcript segments into semantic blocks (~target duration).",
    impl_path="src/acfv/modular/plugins/semantic_merge.py",
    default_params={},
)


__all__ = ["spec"]
