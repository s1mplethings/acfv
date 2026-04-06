from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from acfv import config as app_config
from acfv.processing.subtitle_contract import generate_subtitle
from acfv.steps.subtitle_generator.segmenter import (
    SegmenterConfig,
    retime_captions,
    segment_words_into_captions,
)

logger = logging.getLogger(__name__)


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _get_config_value(name: str, fallback: Any) -> Any:
    cm = getattr(app_config, "config_manager", None)
    if cm is None:
        return fallback
    value = cm.get(name, fallback)
    return value if value is not None else fallback


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    return re.findall(r"\S+", text)


def load_transcription_words(transcription_path: Path) -> List[Dict[str, Any]]:
    payload = _read_json(transcription_path)
    if not isinstance(payload, dict):
        return []
    segments = payload.get("segments", [])
    words: List[Dict[str, Any]] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", 0.0))
        if end <= start:
            continue
        if isinstance(seg.get("words"), list):
            for w in seg.get("words"):
                if not isinstance(w, dict):
                    continue
                w_start = float(w.get("start", start))
                w_end = float(w.get("end", w_start + 0.05))
                w_text = str(w.get("text", "")).strip()
                if w_end <= w_start or not w_text:
                    continue
                words.append({"start": w_start, "end": w_end, "text": w_text})
            continue
        text = str(seg.get("text", "")).strip()
        tokens = _tokenize(text)
        if not tokens:
            continue
        total = len(tokens)
        dur = max(end - start, 0.001)
        step = dur / total
        for idx, token in enumerate(tokens):
            w_start = start + idx * step
            w_end = min(end, w_start + step)
            words.append({"start": w_start, "end": w_end, "text": token})
    words.sort(key=lambda w: (w["start"], w["end"]))
    return words


def load_speaker_segments(work_dir: Path) -> Dict[str, Any]:
    speaker_dir = work_dir / "speaker_separation"
    result_path = speaker_dir / "speaker_separation_result.json"
    payload = _read_json(result_path) if result_path.exists() else None
    if isinstance(payload, dict) and payload.get("segments"):
        return payload

    fallback_path = work_dir / "speaker_segments.json"
    payload = _read_json(fallback_path)
    if isinstance(payload, dict) and payload.get("segments"):
        return payload
    if isinstance(payload, list):
        return {"segments": payload}
    return {}


def pick_primary_speaker(payload: Dict[str, Any], override: Optional[str]) -> Optional[str]:
    if override:
        return override
    host = payload.get("host_speaker")
    if host:
        return str(host)
    segments = payload.get("segments", [])
    if not segments:
        return None
    duration_by_speaker: Dict[str, float] = {}
    for seg in segments:
        speaker = str(seg.get("speaker", ""))
        if not speaker:
            continue
        duration = float(seg.get("duration", 0.0))
        if duration <= 0:
            duration = max(0.0, float(seg.get("end", 0.0)) - float(seg.get("start", 0.0)))
        duration_by_speaker[speaker] = duration_by_speaker.get(speaker, 0.0) + duration
    if not duration_by_speaker:
        return None
    return max(duration_by_speaker.items(), key=lambda item: item[1])[0]


def filter_words_by_speaker(words: List[Dict[str, Any]], payload: Dict[str, Any], speaker: str) -> List[Dict[str, Any]]:
    segments = [seg for seg in payload.get("segments", []) if seg.get("speaker") == speaker]
    if not segments:
        return []
    segments.sort(key=lambda s: float(s.get("start", 0.0)))
    filtered: List[Dict[str, Any]] = []
    seg_idx = 0
    for word in words:
        w_mid = (float(word["start"]) + float(word["end"])) * 0.5
        while seg_idx < len(segments) and float(segments[seg_idx].get("end", 0.0)) < w_mid:
            seg_idx += 1
        if seg_idx >= len(segments):
            break
        seg = segments[seg_idx]
        if float(seg.get("start", 0.0)) <= w_mid <= float(seg.get("end", 0.0)):
            filtered.append(word)
    return filtered


def run_generate_streamer_subtitles(run_dir: str | Path, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    run_path = Path(run_dir)
    work_dir = run_path / "work"
    transcription_path = work_dir / "transcription.json"
    if not transcription_path.exists():
        return {"status": "missing_transcription", "work_dir": str(work_dir)}

    speaker_payload = load_speaker_segments(work_dir)
    if not speaker_payload.get("segments"):
        return {"status": "missing_speaker_segments", "work_dir": str(work_dir)}

    words = load_transcription_words(transcription_path)
    if not words:
        return {"status": "missing_words", "work_dir": str(work_dir)}

    override = None
    if isinstance(config, dict):
        override = config.get("primary_speaker")
    if override is None:
        override = _get_config_value("STREAMER_PRIMARY_SPEAKER", None)

    primary = pick_primary_speaker(speaker_payload, override)
    if not primary:
        return {"status": "missing_primary_speaker", "work_dir": str(work_dir)}

    speaker_words = filter_words_by_speaker(words, speaker_payload, primary)
    if not speaker_words:
        return {"status": "no_words_for_speaker", "speaker": primary, "work_dir": str(work_dir)}

    cfg = SegmenterConfig()
    cfg.max_chars_per_line = int(_get_config_value("STREAMER_SUB_MAX_CHARS", cfg.max_chars_per_line))
    cfg.max_lines = int(_get_config_value("STREAMER_SUB_MAX_LINES", cfg.max_lines))
    cfg.target_duration = float(_get_config_value("STREAMER_SUB_TARGET_DUR", cfg.target_duration))
    cfg.min_duration = float(_get_config_value("STREAMER_SUB_MIN_DUR", cfg.min_duration))
    cfg.max_duration = float(_get_config_value("STREAMER_SUB_MAX_DUR", cfg.max_duration))
    cfg.pause_split = float(_get_config_value("STREAMER_SUB_PAUSE_SPLIT", cfg.pause_split))

    captions = segment_words_into_captions(speaker_words, cfg)
    captions = retime_captions(captions, lead_in=0.12, lead_out=0.06)
    if not captions:
        return {"status": "no_captions", "speaker": primary, "work_dir": str(work_dir)}

    out_dir = work_dir
    srt_payload = {
        "segments": [{"start": c["start"], "end": c["end"], "text": c["text"]} for c in captions],
        "format": "srt",
        "out_dir": str(out_dir),
        "source_name": "subtitles_streamer",
    }
    ass_payload = dict(srt_payload)
    ass_payload["format"] = "ass"

    srt_result = generate_subtitle(srt_payload)
    ass_result = generate_subtitle(ass_payload)

    debug = {
        "schema_version": "1.0.0",
        "speaker": primary,
        "caption_count": len(captions),
        "config": asdict(cfg),
        "srt": srt_result.get("subtitle_path"),
        "ass": ass_result.get("subtitle_path"),
    }
    _write_json(out_dir / "subtitles_streamer.debug.json", debug)

    return {
        "status": "ok",
        "speaker": primary,
        "srt_path": srt_result.get("subtitle_path"),
        "ass_path": ass_result.get("subtitle_path"),
        "caption_count": len(captions),
    }


__all__ = ["run_generate_streamer_subtitles", "load_transcription_words", "load_speaker_segments"]
