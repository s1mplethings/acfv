from __future__ import annotations

import re
from typing import Dict, List, Optional


def parse_preference_text(text: str) -> Dict[str, object]:
    """
    Very lightweight preference extractor.

    Rules:
    - "不要|排除|不想要"+"词" => exclude_tags
    - "+标签" => include_tags
    - "时长>60" / "duration>60" => min/max duration
    """
    include_tags: List[str] = []
    exclude_tags: List[str] = []
    min_duration: Optional[float] = None
    max_duration: Optional[float] = None
    min_emotion: Optional[float] = None
    min_talk_ratio: Optional[float] = None

    tokens = re.split(r"[,;，；\s]+", text.strip())
    for tok in tokens:
        if not tok:
            continue
        if tok.startswith("+"):
            include_tags.append(tok[1:])
            continue
        if tok.startswith("-"):
            exclude_tags.append(tok[1:])
            continue
        if re.search(r"(不要|排除|不想要)", tok):
            tag = re.sub(r"(不要|排除|不想要)", "", tok)
            if tag:
                exclude_tags.append(tag)
            continue
        dur_gt = re.match(r"(duration|时长)[>：:](\d+)", tok, re.IGNORECASE)
        dur_lt = re.match(r"(duration|时长)[<：:](\d+)", tok, re.IGNORECASE)
        emo_gt = re.match(r"(emotion|情绪)[>：:](0?\.\d+|\d+)", tok, re.IGNORECASE)
        talk_gt = re.match(r"(talk|对话|说话)[>：:](0?\.\d+|\d+)", tok, re.IGNORECASE)
        if dur_gt:
            min_duration = float(dur_gt.group(2))
            continue
        if dur_lt:
            max_duration = float(dur_lt.group(2))
            continue
        if emo_gt:
            min_emotion = float(emo_gt.group(2))
            continue
        if talk_gt:
            min_talk_ratio = float(talk_gt.group(2))
            continue
        include_tags.append(tok)

    return {
        "include_tags": include_tags,
        "exclude_tags": exclude_tags,
        "min_duration": min_duration,
        "max_duration": max_duration,
        "min_emotion": min_emotion,
        "min_talk_ratio": min_talk_ratio,
    }
