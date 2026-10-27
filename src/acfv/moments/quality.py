from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .models import Moment


class MomentQualityAction(str, Enum):
    KEEP = "KEEP"
    KEEP_REACTION = "KEEP_REACTION"
    SUPPORTING = "SUPPORTING"
    SUPPRESS = "SUPPRESS"
    STRUCTURAL_DUPLICATE = "STRUCTURAL_DUPLICATE"


@dataclass(frozen=True)
class MomentQualityDecision:
    moment_id: str
    action: MomentQualityAction
    reason: str
    duplicate_of: str | None = None


_REACTION = re.compile(
    r"^(?:oh+|ah+|wow+|whoa+|no+|yes+|what+|huh+|ha(?:ha)+|lmao+|lol+|scream(?:ing)?|laugh(?:ing)?)[!?！。\s]*$",
    re.IGNORECASE,
)
_EVENT_TERMS = {
    "afraid", "angry", "awesome", "camera", "cute", "dead", "died", "dumbass", "evil",
    "fuck", "god", "help", "hungry", "laugh", "laughing", "lost", "love", "scared",
    "scream", "sorry", "stop", "wicked", "win", "won", "wrong",
}


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+|[\u3400-\u9fff]|[\u3040-\u30ff]+", text.casefold())


def _normalized(text: str) -> str:
    return " ".join(_tokens(text))


def _iou(left: Moment, right: Moment) -> float:
    intersection = max(0, min(left.end_ms, right.end_ms) - max(left.start_ms, right.start_ms))
    union = max(left.end_ms, right.end_ms) - min(left.start_ms, right.start_ms)
    return intersection / union if union > 0 else 0.0


def _evidence_identity(moment: Moment) -> set[tuple]:
    try:
        rows = json.loads(moment.evidence_json or "[]")
    except (json.JSONDecodeError, TypeError):
        return set()
    return {
        (
            item.get("type"), item.get("artifact"), int(item.get("start_ms", -1)),
            int(item.get("end_ms", -1)), _normalized(str(item.get("raw_text") or item.get("text") or "")),
        )
        for item in rows if isinstance(item, dict)
    }


def _reaction_signal(text: str, tokens: list[str]) -> bool:
    if _REACTION.fullmatch(text.strip()):
        return True
    emphatic = bool(re.search(r"[!?！？]", text))
    return emphatic and bool(set(tokens) & _EVENT_TERMS)


def classify_moments(moments: Iterable[Moment]) -> list[MomentQualityDecision]:
    ordered = sorted(moments, key=lambda item: (item.recording_id, item.start_ms, item.end_ms, item.id))
    frequency: dict[tuple[str, str], int] = {}
    for item in ordered:
        key = (item.recording_id, _normalized(item.transcript_text))
        frequency[key] = frequency.get(key, 0) + 1
    decisions: list[MomentQualityDecision] = []
    previous_by_recording: dict[str, list[Moment]] = {}
    for moment in ordered:
        duplicate_of = None
        current_evidence = _evidence_identity(moment)
        prior_rows = previous_by_recording.setdefault(moment.recording_id, [])
        for prior in reversed(prior_rows[-5:]):
            same_text = _normalized(prior.transcript_text) == _normalized(moment.transcript_text)
            evidence_overlap = current_evidence & _evidence_identity(prior)
            if _iou(prior, moment) >= 0.8 and (same_text or bool(evidence_overlap)):
                duplicate_of = prior.id
                break
        if duplicate_of:
            decisions.append(MomentQualityDecision(moment.id, MomentQualityAction.STRUCTURAL_DUPLICATE, "same overlapping source evidence", duplicate_of))
            prior_rows.append(moment)
            continue

        tokens = _tokens(moment.transcript_text)
        event_signal = bool(moment.chat_text.strip() or moment.visual_text.strip() or moment.ocr_text.strip())
        if len(tokens) < 4 and _reaction_signal(moment.transcript_text, tokens):
            action, reason = MomentQualityAction.KEEP_REACTION, "short reaction is a product event"
        elif len(tokens) < 4 and event_signal:
            action, reason = MomentQualityAction.SUPPORTING, "short transcript has chat/visual event support"
        elif len(tokens) == 3 and moment.end_ms - moment.start_ms >= 3_000 and frequency[(moment.recording_id, _normalized(moment.transcript_text))] == 1:
            action, reason = MomentQualityAction.SUPPORTING, "short unique statement has sustained source evidence"
        elif len(tokens) < 4:
            action, reason = MomentQualityAction.SUPPRESS, "isolated low-information ASR fragment without event support"
        else:
            action, reason = MomentQualityAction.KEEP, "sufficient semantic content"
        decisions.append(MomentQualityDecision(moment.id, action, reason))
        prior_rows.append(moment)
    return decisions


def repair_moments(repository, *, creator_id: str, dry_run: bool = True) -> dict:
    moments = repository.list_moments(creator_id=creator_id)
    decisions = classify_moments(moments)
    removable = [
        item.moment_id for item in decisions
        if item.action in {MomentQualityAction.SUPPRESS, MomentQualityAction.STRUCTURAL_DUPLICATE}
        and not repository.moment_has_product_references(item.moment_id)
    ]
    if not dry_run and removable:
        repository.delete_moments(removable)
    counts = {action.value: sum(item.action == action for item in decisions) for action in MomentQualityAction}
    return {
        "dry_run": dry_run,
        "before_count": len(moments),
        "after_count": len(moments) - len(removable),
        "counts": counts,
        "removed_ids": removable,
        "decisions": [
            {"moment_id": item.moment_id, "action": item.action.value, "reason": item.reason, "duplicate_of": item.duplicate_of}
            for item in decisions
        ],
    }
