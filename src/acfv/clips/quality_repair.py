from __future__ import annotations

from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from enum import Enum
import hashlib
import re
from typing import Any, Iterable, Mapping, Sequence

from .candidates import temporal_iou


class IssueScope(str, Enum):
    EVENT_SHARED = "EVENT_SHARED"
    PROFILE_SPECIFIC = "PROFILE_SPECIFIC"


def event_issue_identity(issue: Mapping[str, Any], *, event_id: str, profile: str) -> dict[str, Any]:
    """Attach stable event/profile identity without collapsing independent risks."""
    row = dict(issue)
    scope = IssueScope(str(row.get("issue_scope") or IssueScope.EVENT_SHARED.value))
    consequence = str(row.get("semantic_consequence") or row.get("type") or "UNKNOWN")
    root = str(row.get("root_cause_key") or row.get("issue_id") or consequence)
    span = (int(row.get("start_ms") or 0), int(row.get("end_ms") or row.get("start_ms") or 0))
    parts = [event_id, root, consequence, *span]
    if scope is IssueScope.PROFILE_SPECIFIC:
        parts.append(profile)
    row.update({
        "event_id": event_id, "profile": profile, "issue_scope": scope.value,
        "event_issue_identity": hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:20],
    })
    return row


def deduplicate_event_profile_issues(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Count shared ASR/translation roots once while retaining hard consequences."""
    selected: dict[str, dict[str, Any]] = {}
    for original in rows:
        row = dict(original)
        identity = str(row.get("event_issue_identity") or "")
        if not identity:
            row = event_issue_identity(row, event_id=str(row.get("event_id") or ""),
                                       profile=str(row.get("profile") or ""))
            identity = row["event_issue_identity"]
        current = selected.get(identity)
        if current is None:
            selected[identity] = row
            continue
        rank = {"INFO": 0, "WARNING": 1, "HIGH": 2, "CRITICAL": 3}
        if (bool(row.get("hard_blocker")), rank.get(str(row.get("severity")), -1)) > (
            bool(current.get("hard_blocker")), rank.get(str(current.get("severity")), -1)
        ):
            selected[identity] = row
    return sorted(selected.values(), key=lambda row: (
        str(row.get("event_id")), int(row.get("start_ms") or 0), str(row.get("event_issue_identity"))
    ))


@dataclass(frozen=True)
class EventDuplicateCandidate:
    event_id: str
    recording_id: str
    start_ms: int
    end_ms: int
    transcript: str
    evidence_coverage: float = 0.0
    semantic_completeness: float = 0.0
    unresolved_language_risk: float = 0.0
    watchability: float = 0.0
    boundary_quality: float = 0.0


@dataclass(frozen=True)
class EventDuplicateCluster:
    cluster_id: str
    event_ids: tuple[str, ...]
    winner_event_id: str
    suppressed_event_ids: tuple[str, ...]
    evidence: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _lexical_similarity(left: str, right: str) -> float:
    normalize = lambda value: " ".join(re.findall(r"[\w']+", value.casefold()))
    return SequenceMatcher(None, normalize(left), normalize(right)).ratio()


def cluster_cross_event_duplicates(
    candidates: Sequence[EventDuplicateCandidate], *,
    semantic_similarity: Mapping[tuple[str, str], float] | None = None,
    direct_iou: float = 0.90, combined_iou: float = 0.60,
    lexical_threshold: float = 0.78, semantic_threshold: float = 0.82,
) -> list[EventDuplicateCluster]:
    """Cluster only different events; profile variants never enter this API."""
    semantic_similarity = semantic_similarity or {}
    parent: dict[str, str] = {item.event_id: item.event_id for item in candidates}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a

    edges: list[dict[str, Any]] = []
    for index, left in enumerate(candidates):
        for right in candidates[index + 1:]:
            if left.event_id == right.event_id or left.recording_id != right.recording_id:
                continue
            iou = temporal_iou(left.start_ms, left.end_ms, right.start_ms, right.end_ms)
            lexical = _lexical_similarity(left.transcript, right.transcript)
            semantic = float(semantic_similarity.get((left.event_id, right.event_id),
                                                       semantic_similarity.get((right.event_id, left.event_id), lexical)))
            suspect = iou >= direct_iou or (
                iou >= combined_iou and lexical >= lexical_threshold and semantic >= semantic_threshold
            )
            if suspect:
                union(left.event_id, right.event_id)
                edges.append({"left": left.event_id, "right": right.event_id,
                              "temporal_iou": round(iou, 4), "lexical_similarity": round(lexical, 4),
                              "semantic_similarity": round(semantic, 4)})
    grouped: dict[str, list[EventDuplicateCandidate]] = {}
    for item in candidates:
        grouped.setdefault(find(item.event_id), []).append(item)
    clusters: list[EventDuplicateCluster] = []
    for members in grouped.values():
        if len({item.event_id for item in members}) < 2:
            continue
        winner = max(members, key=lambda item: (
            item.evidence_coverage, item.semantic_completeness, -item.unresolved_language_risk,
            item.watchability, item.boundary_quality,
        ))
        member_ids = {item.event_id for item in members}
        cluster_edges = tuple(edge for edge in edges if edge["left"] in member_ids and edge["right"] in member_ids)
        digest = hashlib.sha256("|".join(sorted(member_ids)).encode()).hexdigest()[:16]
        clusters.append(EventDuplicateCluster(
            cluster_id=f"event-duplicate:{digest}", event_ids=tuple(sorted(member_ids)),
            winner_event_id=winner.event_id, suppressed_event_ids=tuple(sorted(member_ids - {winner.event_id})),
            evidence=cluster_edges,
        ))
    return sorted(clusters, key=lambda item: item.cluster_id)


_CONTENT_WEIGHTS = {
    "reaction": {"setup": .20, "trigger": .25, "reaction": .25, "payoff": .30},
    "chatting": {"topic": .25, "argument": .40, "conclusion": .35},
    "collab": {"setup": .25, "interaction": .40, "response": .35},
    "simulation": {"problem": .30, "action": .35, "result": .35},
}


def content_specific_watchability(content_type: str, features: Mapping[str, float]) -> dict[str, Any]:
    """Structural, content-aware score; never claims funny or publishable."""
    kind = content_type.casefold()
    weights = _CONTENT_WEIGHTS.get(kind, _CONTENT_WEIGHTS["chatting"])
    structural = sum(weights[name] * max(0.0, min(1.0, float(features.get(name, 0.0))))
                     for name in weights)
    global_score = sum((
        .25 * float(features.get("evidence_coverage", 0.0)),
        .20 * float(features.get("self_contained", 0.0)),
        .20 * float(features.get("boundary_quality", 0.0)),
        .15 * float(features.get("language_quality", 0.0)),
    ))
    penalties = .12 * float(features.get("unrelated_padding", 0.0)) + .08 * float(
        features.get("duplicate_penalty", 0.0)
    )
    return {"content_type": kind, "structural": round(structural, 4),
            "total": round(max(0.0, min(1.0, .55 * structural + global_score - penalties)), 4),
            "human_only": ["FUNNY", "INTERESTING", "GOOD_PACING", "PUBLISHABLE"]}


__all__ = [
    "EventDuplicateCandidate", "EventDuplicateCluster", "IssueScope",
    "cluster_cross_event_duplicates", "content_specific_watchability",
    "deduplicate_event_profile_issues", "event_issue_identity",
]
