from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Dict, List


_PUNCT = set("，。！？,.!?;:、")


@dataclass
class SegmenterConfig:
    max_chars_per_line: int = 16
    max_lines: int = 2
    target_duration: float = 1.6
    min_duration: float = 0.7
    max_duration: float = 3.2
    pause_split: float = 0.28
    no_single_char_line: bool = True


def _count_chars(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", text or ""))


def _wrap_text(text: str, max_chars: int, max_lines: int, no_single_char_line: bool) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    if " " in text:
        words = text.split()
    else:
        words = list(text)

    lines: List[str] = []
    current = ""
    for word in words:
        if not current:
            current = word
            continue
        if _count_chars(current + (" " if " " in text else "") + word) <= max_chars:
            current = current + (" " if " " in text else "") + word
        else:
            lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)

    if no_single_char_line and len(lines) >= 2:
        cleaned: List[str] = []
        for idx, line in enumerate(lines):
            if _count_chars(line) <= 1 and idx < len(lines) - 1:
                lines[idx + 1] = (line + lines[idx + 1]).strip()
            else:
                cleaned.append(line)
        lines = cleaned

    return "\n".join(lines[:max_lines])


def _boundary_score(word_text: str, gap: float, max_chars: int) -> float:
    score = 0.0
    if word_text and word_text[-1] in _PUNCT:
        score += 3.0
    if gap > 0:
        score += min(2.0, 2.0 * (gap / 0.6))
    if max_chars <= 0:
        score += 10.0
    return score


def segment_words_into_captions(words: List[Dict[str, float | str]], cfg: SegmenterConfig) -> List[Dict[str, float | str]]:
    if not words:
        return []

    captions: List[Dict[str, float | str]] = []
    cur_words: List[Dict[str, float | str]] = []
    cur_start = float(words[0]["start"])
    cur_end = float(words[0]["end"])
    cur_text = ""

    def flush() -> None:
        nonlocal cur_words, cur_text, cur_start, cur_end
        text = _wrap_text(cur_text, cfg.max_chars_per_line, cfg.max_lines, cfg.no_single_char_line)
        if text:
            captions.append({"start": cur_start, "end": cur_end, "text": text})
        cur_words = []
        cur_text = ""

    for idx, word in enumerate(words):
        w_text = str(word.get("text", "")).strip()
        if not w_text:
            continue
        if not cur_words:
            cur_start = float(word["start"])
            cur_end = float(word["end"])
            cur_text = w_text
        else:
            cur_end = max(cur_end, float(word["end"]))
            cur_text = (cur_text + " " + w_text).strip()

        cur_words.append(word)

        if idx == len(words) - 1:
            flush()
            break

        next_word = words[idx + 1]
        gap = max(0.0, float(next_word["start"]) - cur_end)
        duration = max(cur_end - cur_start, 0.0)
        char_count = _count_chars(cur_text)
        max_chars = cfg.max_chars_per_line * cfg.max_lines
        bscore = _boundary_score(w_text, gap, max_chars - char_count)

        force_cut = duration >= cfg.max_duration or char_count >= max_chars
        should_cut = False
        if force_cut:
            should_cut = True
        elif duration >= cfg.target_duration and bscore >= 2.0:
            should_cut = True
        elif gap >= cfg.pause_split and duration >= cfg.min_duration:
            should_cut = True

        if should_cut and duration >= cfg.min_duration:
            flush()

    return captions


def retime_captions(
    captions: List[Dict[str, float | str]],
    lead_in: float = 0.12,
    lead_out: float = 0.06,
) -> List[Dict[str, float | str]]:
    if not captions:
        return []
    results: List[Dict[str, float | str]] = []
    for idx, cap in enumerate(captions):
        start = float(cap["start"]) - lead_in
        end = float(cap["end"]) + lead_out
        if idx > 0:
            prev_end = float(results[-1]["end"])
            start = max(start, prev_end)
        if idx < len(captions) - 1:
            next_start = float(captions[idx + 1]["start"])
            end = min(end, next_start)
        if end <= start:
            end = start + 0.05
        results.append({"start": max(0.0, start), "end": max(0.0, end), "text": cap["text"]})
    return results

