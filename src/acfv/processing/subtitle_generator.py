import os
import re
import json
import math
from typing import List, Dict, Any, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def _read_transcription(transcription_file: str) -> List[Dict[str, Any]]:
    if not transcription_file or not os.path.exists(transcription_file):
        return []
    try:
        with open(transcription_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and 'segments' in data:
            return data.get('segments', [])
        if isinstance(data, list):
            return data
    except Exception:
        return []
    return []


def _parse_clip_time_from_name(filename: str) -> Tuple[float, float]:
    # clip_001_123.4s-234.5s.mp4
    m = re.search(r"clip_\d+_(\d+(?:\.\d+)?)s-(\d+(?:\.\d+)?)s\.mp4$", filename)
    if m:
        return float(m.group(1)), float(m.group(2))
    # fallback: no match
    return 0.0, 0.0


def _format_srt_time(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - math.floor(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _split_sentences(text: str) -> List[str]:
    if not text:
        return []
    # Split by Chinese and English punctuation, keep delimiters
    parts = re.split(r"([。！？!?；;])", text)
    sentences = []
    buf = ""
    for i in range(0, len(parts), 2):
        chunk = parts[i].strip()
        delim = parts[i+1] if i+1 < len(parts) else ""
        if chunk:
            buf = chunk + (delim if delim else "")
            sentences.append(buf.strip())
            buf = ""
    # Fallback: if nothing split, try by commas
    if not sentences and text:
        sentences = [t.strip() for t in re.split(r"[，,]", text) if t.strip()]
    return sentences


def _semantic_merge(sentences: List[Dict[str, Any]], sim_threshold: float, max_gap: float, min_chars: int) -> List[Dict[str, Any]]:
    if not sentences:
        return []
    texts = [s['text'] for s in sentences]
    if not any(texts):
        return sentences
    # Build TF-IDF vectors for similarity
    try:
        vectorizer = TfidfVectorizer(max_features=1000, ngram_range=(1, 2))
        X = vectorizer.fit_transform(texts)
        sim = cosine_similarity(X)
    except Exception:
        sim = None

    merged: List[Dict[str, Any]] = []
    cur = sentences[0].copy()
    for i in range(1, len(sentences)):
        nxt = sentences[i]
        time_gap = max(0.0, nxt['start'] - cur['end'])
        cur_len = len(cur['text'])
        nxt_len = len(nxt['text'])
        similar = False
        if sim is not None:
            similar = (sim[i-1][i] if i-1 < sim.shape[0] and i < sim.shape[1] else 0.0) >= sim_threshold
        # Merge if very short or similar and gap small
        if (cur_len < min_chars or nxt_len < min_chars or similar) and time_gap <= max_gap:
            cur['text'] = (cur['text'] + " " + nxt['text']).strip()
            cur['end'] = max(cur['end'], nxt['end'])
        else:
            merged.append(cur)
            cur = nxt.copy()
    merged.append(cur)
    return merged


def _build_sentence_chunks(segments: List[Dict[str, Any]], clip_start: float, clip_end: float) -> List[Dict[str, Any]]:
    # For each original segment overlapping with [clip_start, clip_end], split into sentences
    chunks: List[Dict[str, Any]] = []
    for seg in segments:
        s = float(seg.get('start', 0.0))
        e = float(seg.get('end', 0.0))
        if e <= clip_start or s >= clip_end:
            continue
        text = (seg.get('text') or "").strip()
        if not text:
            continue
        # Trim to clip window
        s2 = max(s, clip_start)
        e2 = min(e, clip_end)
        if e2 <= s2:
            continue
        sentences = _split_sentences(text)
        if not sentences:
            continue
        # Allocate time proportionally within this segment
        total_chars = sum(len(t) for t in sentences)
        if total_chars <= 0:
            continue
        dur = e2 - s2
        t_cursor = s2
        for sent in sentences:
            frac = len(sent) / total_chars if total_chars > 0 else 0
            sd = t_cursor
            ed = min(clip_end, sd + dur * frac)
            t_cursor = ed
            chunks.append({'start': sd, 'end': ed, 'text': sent})
    # Ensure ordered
    chunks.sort(key=lambda x: (x['start'], x['end']))
    return chunks


def generate_semantic_subtitles_for_clips(output_clips_dir: str, transcription_file: str, cfg_manager, clip_paths: List[str]) -> int:
    """Generate SRT subtitles per clip based on semantic sentence splitting and light merging.

    Returns number of subtitle files written.
    """
    segments = _read_transcription(transcription_file)
    if not segments:
        return 0

    # Configs
    sim_threshold = float(cfg_manager.get("SEMANTIC_SIMILARITY_THRESHOLD", 0.65) or 0.65)
    max_gap = float(cfg_manager.get("SEMANTIC_MAX_TIME_GAP", 2.0) or 2.0)
    min_chars = int(cfg_manager.get("SUBTITLE_MIN_SENTENCE_CHARS", 6) or 6)

    written = 0
    for clip_path in clip_paths:
        try:
            base = os.path.basename(clip_path)
            s, e = _parse_clip_time_from_name(base)
            if e <= s:
                # fallback: no times -> skip
                continue
            # Collect sentence chunks
            chunks = _build_sentence_chunks(segments, s, e)
            # Merge semantically
            chunks = _semantic_merge(chunks, sim_threshold, max_gap, min_chars)
            # Filter very short items
            chunks = [c for c in chunks if len((c['text'] or '').strip()) >= 1 and (c['end'] - c['start']) > 0.05]
            if not chunks:
                continue
            # Write SRT
            srt_path = os.path.splitext(clip_path)[0] + ".srt"
            with open(srt_path, 'w', encoding='utf-8') as f:
                for idx, c in enumerate(chunks, 1):
                    f.write(f"{idx}\n")
                    f.write(f"{_format_srt_time(c['start']-s)} --> {_format_srt_time(c['end']-s)}\n")
                    f.write((c['text'] or '').strip() + "\n\n")
            written += 1
        except Exception:
            # Skip errors for a single clip
            continue
    return written
