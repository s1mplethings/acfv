from __future__ import annotations

import json
import hashlib
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from acfv.backend.service import render_review_clip
from acfv.library.models import Clip
from acfv.library.repository import LibraryRepository
from acfv.retrieval.query import SearchResult


class CandidateType(str, Enum):
    MOST_RELEVANT = "MOST_RELEVANT"
    MOST_COMPLETE = "MOST_COMPLETE"
    MOST_WATCHABLE = "MOST_WATCHABLE"


class RejectionReason(str, Enum):
    LOW_WATCHABILITY = "LOW_WATCHABILITY"
    QUERY_MISMATCH = "QUERY_MISMATCH"
    INCOMPLETE_CONTEXT = "INCOMPLETE_CONTEXT"
    LOW_INFORMATION = "LOW_INFORMATION"
    SOURCE_EDGE = "SOURCE_EDGE"
    NO_PAYOFF = "NO_PAYOFF"
    NO_HOOK = "NO_HOOK"


@dataclass(frozen=True)
class WatchabilityScore:
    query_relevance: float
    self_containedness: float
    hook_strength: float
    setup_completeness: float
    event_change: float
    emotional_change: float
    reaction_strength: float
    chat_interaction: float
    visual_change: float
    payoff_completeness: float
    sentence_completeness: float
    context_sufficiency: float
    dead_air_penalty: float
    jargon_dependency_penalty: float
    source_edge_penalty: float
    low_information_penalty: float
    total: float


@dataclass
class ClipCandidate:
    candidate_id: str
    candidate_type: CandidateType
    moment_id: str
    recording_id: str
    query: str
    start_ms: int
    end_ms: int
    retrieval_rank: int
    retrieval_score: float
    watchability: WatchabilityScore
    rejection_reasons: list[str] = field(default_factory=list)
    source_edge_override: bool = False
    source_edge_override_reason: str = ""
    selected: bool = False
    preview_path: str | None = None
    event_id: str | None = None
    same_event_variant: bool = False
    preview_metadata: dict[str, Any] | None = None

    @property
    def eligible(self) -> bool:
        return not self.rejection_reasons

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["candidate_type"] = self.candidate_type.value
        value["eligible"] = self.eligible
        value["duration_ms"] = self.end_ms - self.start_ms
        value["watchability_score"] = self.watchability.total
        return value


_REACTION = re.compile(
    r"\b(?:oh|wow|whoa|wait|what|why|no|help|scared|scary|scream|gasp|laugh|haha|holy|fuck|shit|jesus|run|behind me|i'm leaving)\b",
    re.IGNORECASE,
)
_PAYOFF = re.compile(
    r"\b(?:won|lost|lose|dead|died|killed|escaped|finished|over|made it|didn't|did not|turns out|that's why|right\?|you screamed|game over)\b",
    re.IGNORECASE,
)
_SETUP = re.compile(
    r"\b(?:because|before|when|if|need|have to|going to|trying|there(?:'s| is)|this is|we are|i am|i'm)\b",
    re.IGNORECASE,
)
_CJK_REACTION = re.compile(
    r"(?:うわ|えっ|やば|怖|びっくり|待って|何|なに|まじ|くそ|哇|啊|什么|等等|救命|吓|天啊|卧槽|糟|快跑)"
)
_CJK_PAYOFF = re.compile(
    r"(?:勝った|負けた|死んだ|倒した|逃げ(?:た|切)|終わった|できた|成功|失敗|結局|だから|"
    r"赢了|输了|死了|杀了|逃脱|结束了|成功|失败|原来|所以|结果)"
)
_CJK_SETUP = re.compile(
    r"(?:だから|なので|前に|とき|もし|必要|しなければ|つもり|ここ|これは|"
    r"因为|之前|当时|如果|需要|必须|准备|这里|这是)"
)
_JARGON = re.compile(r"\b[A-Z]{2,6}\b|\b\w+(?:API|SDK|CPU|GPU|FMS)\b")


def _semantic_tokens(text: str) -> list[str]:
    """Tokenize Latin and CJK text without treating a full CJK sentence as one word."""
    tokens = re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", text.casefold())
    for sequence in re.findall(r"[\u3040-\u30ff\u3400-\u9fff]+", text):
        if len(sequence) == 1:
            tokens.append(sequence)
        else:
            tokens.extend(sequence[index : index + 2] for index in range(len(sequence) - 1))
    return tokens


def _signal_count(text: str, latin: re.Pattern[str], cjk: re.Pattern[str]) -> int:
    return len(latin.findall(text)) + len(cjk.findall(text))


def temporal_iou(left_start: int, left_end: int, right_start: int, right_end: int) -> float:
    intersection = max(0, min(left_end, right_end) - max(left_start, right_start))
    union = max(left_end, right_end) - min(left_start, right_start)
    return intersection / union if union > 0 else 0.0


def assign_clip_event_ids(
    candidates: Sequence[ClipCandidate],
    *,
    media_hashes: dict[str, str] | None = None,
) -> list[ClipCandidate]:
    """Assign content-event identities without collapsing legitimate variants."""
    representatives: list[ClipCandidate] = []
    hashes = media_hashes or {}
    for candidate in candidates:
        matched = None
        for representative in representatives:
            same_recording = candidate.recording_id == representative.recording_id
            same_parent = candidate.moment_id == representative.moment_id
            same_media = bool(
                hashes.get(candidate.candidate_id)
                and hashes.get(candidate.candidate_id) == hashes.get(representative.candidate_id)
            )
            overlap = temporal_iou(
                candidate.start_ms, candidate.end_ms,
                representative.start_ms, representative.end_ms,
            )
            if (same_recording and (same_parent or overlap >= 0.8)) or same_media:
                matched = representative
                break
        if matched is None:
            raw = f"{candidate.recording_id}:{candidate.moment_id}:{candidate.start_ms}:{candidate.end_ms}"
            candidate.event_id = "event_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
            candidate.same_event_variant = False
            representatives.append(candidate)
        else:
            candidate.event_id = matched.event_id
            candidate.same_event_variant = True
    return list(candidates)


def classify_target_material(*, title: str, content_type: str, expected_event_types: Iterable[str] = ()) -> str:
    """Classify validation material without creator- or game-specific rules."""
    text = " ".join([title, content_type, *expected_event_types]).casefold()
    target_terms = (
        "vtuber", "game", "gaming", "reaction", "chat", "scare", "horror", "fail",
        "jumpscare", "collab", "surprise", "emotion", "streamer",
    )
    engineering_terms = ("tutorial", "lecture", "meeting", "demo", "technical training")
    event_terms = ("reaction", "chat", "scare", "horror", "fail", "jumpscare", "surprise", "emotion")
    if any(term in text for term in engineering_terms) and not any(term in text for term in event_terms):
        return "ENGINEERING_ONLY"
    if any(term in text for term in target_terms):
        return "TARGET_PRODUCT_CONTENT"
    return "ENGINEERING_ONLY"


class ClipCandidateSelector:
    START_EDGE_MS = 10_000
    END_EDGE_MS = 20_000
    MIN_DURATION_MS = 15_000
    MAX_DURATION_MS = 120_000

    def __init__(
        self,
        repository: LibraryRepository,
        *,
        renderer: Callable[..., dict[str, Any]] = render_review_clip,
    ) -> None:
        self.repository = repository
        self.renderer = renderer

    def generate(
        self,
        query: str,
        retrieval_results: Sequence[SearchResult],
        *,
        max_candidates: int = 3,
        source_edge_override: bool = False,
        source_edge_override_reason: str = "",
    ) -> list[ClipCandidate]:
        if not query.strip():
            raise ValueError("Candidate selection requires a query")
        results = list(retrieval_results[:10])
        if not results:
            raise ValueError("Candidate selection requires retrieval evidence")
        if source_edge_override and not source_edge_override_reason.strip():
            raise ValueError("A source-edge override requires a reason")

        ranked: list[tuple[SearchResult, dict[str, Any]]] = []
        for rank, result in enumerate(results, 1):
            moment = self.repository.get_moment(result.moment_id)
            recording = self.repository.get_recording(result.recording_id)
            if moment is None or recording is None:
                continue
            ranked.append((result, {"rank": rank, "moment": moment, "recording": recording}))
        if not ranked:
            raise ValueError("Retrieval results do not resolve to Library state")

        pools: dict[CandidateType, list[ClipCandidate]] = {kind: [] for kind in CandidateType}
        for result, item in ranked:
            for kind in CandidateType:
                start_ms, end_ms = self._boundaries(item["moment"], kind)
                duration = item["recording"].duration_ms
                if duration:
                    start_ms = max(0, start_ms)
                    end_ms = min(int(duration), end_ms)
                candidate = self._candidate(
                    query,
                    result,
                    kind,
                    item["rank"],
                    len(results),
                    start_ms,
                    end_ms,
                    int(duration or 0),
                    source_edge_override,
                    source_edge_override_reason,
                )
                pools[kind].append(candidate)

        def key(candidate: ClipCandidate) -> tuple[float, float, int]:
            if candidate.candidate_type == CandidateType.MOST_RELEVANT:
                primary = candidate.watchability.query_relevance
            elif candidate.candidate_type == CandidateType.MOST_COMPLETE:
                completeness = (
                    candidate.watchability.self_containedness
                    + candidate.watchability.setup_completeness
                    + candidate.watchability.payoff_completeness
                    + candidate.watchability.context_sufficiency
                ) / 4
                primary = 0.30 * candidate.watchability.query_relevance + 0.70 * completeness
            else:
                primary = candidate.watchability.total
            return (1.0 if candidate.eligible else 0.0, primary, -candidate.retrieval_rank)

        chosen: list[ClipCandidate] = []
        used_bounds: set[tuple[str, int, int]] = set()
        for kind in CandidateType:
            for candidate in sorted(pools[kind], key=key, reverse=True):
                identity = (candidate.moment_id, candidate.start_ms, candidate.end_ms)
                if candidate.eligible and identity not in used_bounds:
                    chosen.append(candidate)
                    used_bounds.add(identity)
                    break
        remaining = sorted(
            (item for values in pools.values() for item in values if item.eligible),
            key=lambda item: item.watchability.total,
            reverse=True,
        )
        for candidate in remaining:
            identity = (candidate.moment_id, candidate.start_ms, candidate.end_ms)
            if len(chosen) >= max(3, min(5, max_candidates)):
                break
            if identity not in used_bounds:
                chosen.append(candidate)
                used_bounds.add(identity)
        if not chosen:
            reasons = sorted({reason for values in pools.values() for item in values for reason in item.rejection_reasons})
            raise ValueError("No eligible Clip candidate: " + ", ".join(reasons))
        for number, candidate in enumerate(chosen, 1):
            candidate.candidate_id = f"candidate_{number:02d}"
        assign_clip_event_ids(chosen)
        selected = max(chosen, key=lambda item: item.watchability.total)
        selected.selected = True
        return chosen

    def render_previews(self, candidates: Sequence[ClipCandidate], source_path: str | Path, output_dir: str | Path) -> list[ClipCandidate]:
        output_root = Path(output_dir)
        output_root.mkdir(parents=True, exist_ok=True)
        for candidate in candidates:
            if not candidate.eligible:
                continue
            duration_ms = candidate.end_ms - candidate.start_ms
            output = output_root / f"PREVIEW_PROXY_{candidate.candidate_id}.mp4"
            result = self.renderer(
                video_path=str(source_path),
                output_path=str(output),
                start_ms=candidate.start_ms,
                end_ms=candidate.end_ms,
                subtitle_text="",
                subtitle_style={},
            )
            candidate.preview_path = str(Path(result["output_path"]).resolve())
            candidate.preview_metadata = {
                "artifact_role": "PREVIEW", "is_preview": True,
                "preview_duration": duration_ms / 1000,
                "excluded_from_final_quality_statistics": True,
            }
        return list(candidates)

    def save_proposals(self, candidates: Sequence[ClipCandidate]) -> list[Clip]:
        """Persist candidate boundaries for the existing GUI review workflow."""
        from .service import ClipService

        saved: list[Clip] = []
        service = ClipService(self.repository, renderer=self.renderer)
        for candidate in candidates:
            if not candidate.eligible:
                continue
            clip = service.create_proposal(candidate.moment_id, query=candidate.query)
            metadata = json.loads(clip.reason or "{}")
            metadata["watchability_candidate"] = candidate.to_dict()
            metadata["candidate_id"] = candidate.candidate_id
            metadata["source_edge_override"] = candidate.source_edge_override
            clip.reason = json.dumps(metadata, ensure_ascii=False)
            saved.append(self.repository.save(clip))
        return saved

    @staticmethod
    def write_scores(candidates: Sequence[ClipCandidate], path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"schema_version": "1.0", "candidates": [item.to_dict() for item in candidates]}, ensure_ascii=False, indent=2), encoding="utf-8")
        return output

    def _boundaries(self, moment, kind: CandidateType) -> tuple[int, int]:
        units = self._recording_units(moment.recording_id)
        overlapping = [i for i, unit in enumerate(units) if unit["end_ms"] > moment.start_ms and unit["start_ms"] < moment.end_ms]
        if overlapping:
            first, last = overlapping[0], overlapping[-1]
            start, end = units[first]["start_ms"], units[last]["end_ms"]
        else:
            first = last = 0
            start, end = moment.start_ms, moment.end_ms
        if kind == CandidateType.MOST_RELEVANT:
            before, after = 2_000, 4_000
        elif kind == CandidateType.MOST_COMPLETE:
            before, after = 20_000, 20_000
        else:
            before, after = 8_000, 12_000
        start = max(0, start - before)
        end += after
        if end - start < self.MIN_DURATION_MS:
            end += self.MIN_DURATION_MS - (end - start)
        if end - start > self.MAX_DURATION_MS:
            end = start + self.MAX_DURATION_MS
        return start, end

    def _recording_units(self, recording_id: str) -> list[dict[str, Any]]:
        units: dict[tuple[int, int, str], dict[str, Any]] = {}
        for moment in self.repository.list_moments(recording_id=recording_id):
            try:
                evidence = json.loads(moment.evidence_json or "[]")
            except (json.JSONDecodeError, TypeError):
                evidence = []
            for item in evidence:
                if not isinstance(item, dict) or item.get("type") != "transcript" or not str(item.get("text") or "").strip():
                    continue
                unit = {"start_ms": int(item.get("start_ms", moment.start_ms)), "end_ms": int(item.get("end_ms", moment.end_ms)), "text": str(item["text"]).strip()}
                units[(unit["start_ms"], unit["end_ms"], unit["text"])] = unit
        return sorted(units.values(), key=lambda item: (item["start_ms"], item["end_ms"]))

    def _candidate(
        self,
        query: str,
        result: SearchResult,
        kind: CandidateType,
        rank: int,
        result_count: int,
        start_ms: int,
        end_ms: int,
        source_duration_ms: int,
        source_edge_override: bool,
        source_edge_override_reason: str,
    ) -> ClipCandidate:
        units = [item for item in self._recording_units(result.recording_id) if item["end_ms"] > start_ms and item["start_ms"] < end_ms]
        text = " ".join(item["text"] for item in units).strip() or result.transcript_excerpt
        duration_s = max(0.001, (end_ms - start_ms) / 1000)
        words = _semantic_tokens(text)
        unique_ratio = len(set(words)) / max(1, len(words))
        first = " ".join(words[: max(5, len(words) // 3)])
        last = " ".join(words[-max(5, len(words) // 3) :])
        speech_seconds = sum(max(0, min(end_ms, item["end_ms"]) - max(start_ms, item["start_ms"])) for item in units) / 1000
        density = min(1.0, speech_seconds / duration_s)
        relevance = max(0.0, 1.0 - (rank - 1) / max(1, result_count - 1))
        reaction = min(1.0, _signal_count(text, _REACTION, _CJK_REACTION) / 6)
        hook = min(1.0, (_signal_count(first, _REACTION, _CJK_REACTION) / 2)
                   + (0.2 if re.search(r"[?!！？]", text) else 0.0))
        setup = min(1.0, 0.35 + _signal_count(first, _SETUP, _CJK_SETUP) * 0.2
                    + min(0.25, len(words) / 120))
        payoff = min(1.0, _signal_count(last, _PAYOFF, _CJK_PAYOFF) * 0.35
                     + _signal_count(last, _REACTION, _CJK_REACTION) * 0.1
                     + (0.2 if re.search(r"[.!?。！？][\"'”’)]?\s*$", text) else 0.0))
        sentence = 1.0 if re.search(r"[.!?。！？][\"'”’)]?\s*$", text) else 0.65
        context = min(1.0, 0.3 + min(0.45, len(words) / 100) + (0.25 if setup and payoff else 0.0))
        self_contained = min(1.0, (setup + payoff + sentence + context) / 4)
        chat = min(1.0, len(re.findall(r"\b(?:chat|guys|viewer|comment|said)\b", text, re.I)) / 3)
        visual = min(1.0, len(result.evidence) / 8) if any(item.get("type") in {"visual", "ocr", "scene"} for item in result.evidence) else 0.0
        event = min(1.0, 0.35 * reaction + 0.35 * payoff + 0.3 * visual)
        emotion = min(1.0, reaction * 0.8 + (0.2 if "!" in text else 0.0))
        dead_air = max(0.0, min(1.0, (0.30 - density) / 0.30))
        jargon = min(1.0, len(_JARGON.findall(text)) / max(3, len(words) / 12))
        low_information = max(0.0, min(1.0, (8 - len(set(words))) / 8))
        near_edge = start_ms < self.START_EDGE_MS or (source_duration_ms > 0 and source_duration_ms - end_ms < self.END_EDGE_MS)
        edge_penalty = 0.0 if source_edge_override else (1.0 if near_edge else 0.0)
        positive = (
            relevance * 0.20 + self_contained * 0.14 + hook * 0.09 + setup * 0.09
            + event * 0.08 + emotion * 0.06 + reaction * 0.08 + chat * 0.03
            + visual * 0.03 + payoff * 0.09 + sentence * 0.05 + context * 0.06
        )
        penalties = dead_air * 0.06 + jargon * 0.04 + edge_penalty * 0.20 + low_information * 0.12
        total = round(max(0.0, min(1.0, positive - penalties)), 4)
        score = WatchabilityScore(
            round(relevance, 4), round(self_contained, 4), round(hook, 4), round(setup, 4),
            round(event, 4), round(emotion, 4), round(reaction, 4), round(chat, 4),
            round(visual, 4), round(payoff, 4), round(sentence, 4), round(context, 4),
            round(dead_air, 4), round(jargon, 4), round(edge_penalty, 4), round(low_information, 4), total,
        )
        reasons: list[str] = []
        if near_edge and not source_edge_override:
            reasons.extend([RejectionReason.SOURCE_EDGE.value, RejectionReason.INCOMPLETE_CONTEXT.value])
        if len(set(words)) < 5:
            reasons.append(RejectionReason.LOW_INFORMATION.value)
        if relevance < 0.08:
            reasons.append(RejectionReason.QUERY_MISMATCH.value)
        if hook < 0.15:
            reasons.append(RejectionReason.NO_HOOK.value)
        if payoff < 0.15:
            reasons.append(RejectionReason.NO_PAYOFF.value)
        if total < 0.22:
            reasons.append(RejectionReason.LOW_WATCHABILITY.value)
        return ClipCandidate(
            candidate_id="candidate_pending", candidate_type=kind, moment_id=result.moment_id,
            recording_id=result.recording_id, query=query.strip(), start_ms=start_ms, end_ms=end_ms,
            retrieval_rank=rank, retrieval_score=float(result.score), watchability=score,
            rejection_reasons=list(dict.fromkeys(reasons)), source_edge_override=source_edge_override,
            source_edge_override_reason=source_edge_override_reason.strip(),
        )

