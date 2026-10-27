from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from acfv.retrieval import HybridRetrievalService, SearchResult, SearchScope


NO_EVIDENCE_ANSWER = "没有找到足够明确的视频证据。"
LIVE_NO_EVIDENCE_ANSWER = "当前直播里没有找到足够明确的证据。"
_STOPWORDS = {
    "the", "and", "that", "this", "did", "does", "was", "were", "have", "has", "find",
    "she", "he", "her", "his", "what", "where", "why", "when", "which", "who", "how",
    "moment", "moments", "mention", "mentions", "talk", "talks", "said", "say", "sounds",
}
_YES_NO_PREFIXES = ("did ", "was ", "were ", "is ", "are ", "has ", "have ", "can ", "could ", "will ", "would ")


class ConversationRuntimeMode(str, Enum):
    GROUNDED_LLM = "GROUNDED_LLM"
    EVIDENCE_ONLY = "EVIDENCE_ONLY"
    DEGRADED = "DEGRADED"


@dataclass(frozen=True)
class ConversationAnswer:
    answer: str
    grounded: bool
    confidence: str
    citations: list[str]
    evidence_cards: list[SearchResult]
    runtime_mode: ConversationRuntimeMode = ConversationRuntimeMode.DEGRADED
    citation_details: list[dict[str, Any]] | None = None


class GroundedConversationService:
    def __init__(self, retrieval: HybridRetrievalService, *, llm_client: Any = None) -> None:
        self.retrieval = retrieval
        self.llm_client = llm_client

    def ask(
        self,
        query: str,
        *,
        scope: SearchScope = SearchScope.ENTIRE_LIBRARY,
        creator_id: str | None = None,
        recording_id: str | None = None,
        top_k: int = 8,
    ) -> ConversationAnswer:
        results = self.retrieval.search(
            query,
            top_k=top_k,
            scope=scope,
            creator_id=creator_id,
            recording_id=recording_id,
        )
        supported = [result for result in results if self._supports(query, result)]
        if not supported:
            answer = LIVE_NO_EVIDENCE_ANSWER if scope == SearchScope.LIVE_SESSION else NO_EVIDENCE_ANSWER
            return ConversationAnswer(answer, False, "insufficient", [], [], ConversationRuntimeMode.DEGRADED, [])
        if self.llm_client is None or not getattr(self.llm_client, "available", False):
            return ConversationAnswer(
                f"Evidence-only mode: found {len(supported)} potentially relevant video excerpts.",
                False,
                "evidence_only",
                [],
                supported,
                ConversationRuntimeMode.EVIDENCE_ONLY,
                [],
            )
        evidence_by_id = {f"E{index}": item for index, item in enumerate(supported, 1)}
        try:
            payload = self._complete_grounded(query, evidence_by_id)
        except Exception:
            return ConversationAnswer(
                f"Evidence-only mode: found {len(supported)} potentially relevant video excerpts.",
                False,
                "evidence_only",
                [],
                supported,
                ConversationRuntimeMode.EVIDENCE_ONLY,
                [],
            )
        citations = []
        for item in payload.get("citations", []):
            evidence_id = str(item).strip().upper()
            if evidence_id in evidence_by_id and evidence_id not in citations:
                citations.append(evidence_id)
        if not citations:
            return ConversationAnswer(NO_EVIDENCE_ANSWER, False, "insufficient", [], [], ConversationRuntimeMode.GROUNDED_LLM, [])
        answer = str(payload.get("answer") or "").strip()
        if not answer or answer == NO_EVIDENCE_ANSWER:
            return ConversationAnswer(NO_EVIDENCE_ANSWER, False, "insufficient", [], [], ConversationRuntimeMode.GROUNDED_LLM, [])
        used = [evidence_by_id[item] for item in citations]
        details = [
            {"evidence_id": evidence_id, "moment_id": item.moment_id, "recording_id": item.recording_id, "start_ms": item.start_ms, "end_ms": item.end_ms}
            for evidence_id, item in zip(citations, used)
        ]
        return ConversationAnswer(answer, True, "supported", citations, used, ConversationRuntimeMode.GROUNDED_LLM, details)

    @classmethod
    def _supports(cls, query: str, result: SearchResult) -> bool:
        query_terms = cls._terms(query)
        evidence_text = " ".join(
            [result.summary, result.transcript_excerpt]
            + [str(result.debug.get("winning_representation_excerpt") or "")]
            + [str(item.get("text") or "") for item in result.evidence]
        )
        evidence_terms = cls._terms(evidence_text)
        shared = query_terms & evidence_terms
        lexical_ratio = len(shared) / max(1, len(query_terms))
        reranker_score = result.debug.get("reranker_score") if result.debug else None
        dense_score = result.debug.get("dense_score") if result.debug else None
        final_rank = int(result.debug.get("final_rank") or 999) if result.debug else 999
        yes_no_claim = query.strip().casefold().startswith(_YES_NO_PREFIXES)
        if reranker_score is not None:
            score = float(reranker_score)
            if yes_no_claim:
                # Binary claims are especially vulnerable to direction or
                # negation errors (for example, "stop streaming" versus
                # "come back to streaming"). Require strong cross-encoder
                # agreement in addition to lexical overlap.
                return (
                    len(shared) >= 2
                    and lexical_ratio >= 0.35
                    and score >= -3.0
                    and not cls._polarity_conflict(query, evidence_text)
                )
            lexical_support = (len(shared) >= 2 and lexical_ratio >= 0.25 and score >= -7.5) or (len(shared) >= 1 and score >= -4.5)
            semantic_support = (
                len(shared) >= 1
                and final_rank <= 3
                and dense_score is not None
                and float(dense_score) >= 0.80
                and score >= -7.5
            )
            cross_language_support = cls._cross_language(query, evidence_text) and (
                score >= -3.0 or (dense_score is not None and float(dense_score) >= 0.82 and final_rank <= 3)
            )
            return lexical_support or semantic_support or cross_language_support
        if yes_no_claim:
            return len(shared) >= 2 and lexical_ratio >= 0.35
        return len(shared) >= 2 or lexical_ratio >= 0.35

    @staticmethod
    def _polarity_conflict(query: str, evidence_text: str) -> bool:
        question = query.casefold()
        evidence = evidence_text.casefold()
        predicates = re.findall(r"\b(?:cancel|stop|quit|end|leave|move|close|reject|refuse)\w*\b", question)
        if not predicates:
            return False
        positive_markers = ("scheduled", "valid", "continue", "come back", "return", "resume", "still going")
        for predicate in predicates:
            if re.search(rf"\b(?:not|never|didn't|did not|won't|will not)\s+(?:\w+\s+){{0,2}}{re.escape(predicate)}\w*\b", evidence):
                return True
        return any(marker in evidence for marker in positive_markers) and not any(predicate in evidence for predicate in predicates)

    @staticmethod
    def _cross_language(query: str, evidence_text: str) -> bool:
        query_has_cjk = bool(re.search(r"[\u3400-\u9fff]", query))
        evidence_has_cjk = bool(re.search(r"[\u3400-\u9fff]", evidence_text))
        query_has_latin = bool(re.search(r"[a-z]", query, re.IGNORECASE))
        evidence_has_latin = bool(re.search(r"[a-z]", evidence_text, re.IGNORECASE))
        return (query_has_cjk and evidence_has_latin and not evidence_has_cjk) or (
            evidence_has_cjk and query_has_latin and not query_has_cjk
        )

    @staticmethod
    def _terms(text: str) -> set[str]:
        lowered = text.casefold()
        terms = {
            token
            for token in re.findall(r"[a-z0-9]+", lowered)
            if len(token) >= 3 and token not in _STOPWORDS
        }
        for sequence in re.findall(r"[\u3400-\u9fff]+", lowered):
            if len(sequence) == 1:
                terms.add(sequence)
            else:
                terms.update(sequence[index : index + 2] for index in range(len(sequence) - 1))
        return terms

    def _complete_grounded(self, query: str, evidence_by_id: dict[str, SearchResult]) -> dict:
        system_prompt = (
            "Answer only from the supplied video evidence. Keep the answer short and factual. "
            "Every factual claim must be supported by one or more evidence IDs such as E1. "
            "Return JSON only with answer and citations. Never cite a moment ID or an evidence ID not supplied. "
            f"If evidence is insufficient, answer exactly: {NO_EVIDENCE_ANSWER} and return no citations."
        )
        schema = {
            "type": "object",
            "properties": {"answer": {"type": "string"}, "citations": {"type": "array", "items": {"type": "string"}}},
            "required": ["answer", "citations"],
        }
        prompt = self._prompt(query, evidence_by_id)
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                payload = self.llm_client.complete_json(
                    system_prompt=system_prompt,
                    user_prompt=prompt if attempt == 0 else prompt + "\nRepair: the previous response was malformed. Return the required JSON object only.",
                    schema=schema,
                    temperature=0.0,
                )
                if not isinstance(payload, dict) or not isinstance(payload.get("answer"), str) or not isinstance(payload.get("citations"), list):
                    raise ValueError("Malformed grounded conversation payload")
                return payload
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"Grounded conversation generation failed: {last_error}")

    @staticmethod
    def _prompt(query: str, evidence_by_id: dict[str, SearchResult]) -> str:
        evidence = [
            {
                "evidence_id": evidence_id,
                "recording": item.recording_title,
                "recording_id": item.recording_id,
                "start_ms": item.start_ms,
                "end_ms": item.end_ms,
                "summary": item.summary,
                "transcript": item.transcript_excerpt,
                "retrieval_excerpt": str(item.debug.get("winning_representation_excerpt") or ""),
            }
            for evidence_id, item in evidence_by_id.items()
        ]
        return f"Question: {query}\nEvidence:\n{json.dumps(evidence, ensure_ascii=False)}"
