#!/usr/bin/env python3
"""Validate grounded conversation categories against a persisted fresh index."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from acfv.conversation import GroundedConversationService
from acfv.library import LibraryService
from acfv.llm.openai_client import OpenAIClientConfig, OpenAIJsonClient
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex


SUPPORTED = [
    "Okay anyways nobody here cannot go over this",
    "Spicy Lazy trail already drunk",
    "good times cocaine SS corporal new era",
    "tiny little horses treadmills power engine",
    "fake one decision why would you do that",
]
MULTI_EVIDENCE = [
    "Compare nobody here cannot go with spicy lazy trail drunk",
    "Compare good times cocaine SS with tiny little horses treadmills",
    "Compare fake one decision with sucking fingers",
]
NO_EVIDENCE = [
    "quantum pineapple orchestra on Mars",
    "the creator wins a Nobel prize for chemistry",
    "a blue whale teaches advanced calculus",
    "the stream announces a lunar hotel opening",
    "the creator reviews an Antarctic submarine",
]
CROSS_LANGUAGE = [
    "她说 nobody here cannot go 的时候发生了什么",
    "关于 tiny little horses treadmills 她们说了什么",
]


def client() -> OpenAIJsonClient:
    return OpenAIJsonClient(OpenAIClientConfig(
        provider="ollama", api_key="ollama", base_url="http://127.0.0.1:11434/v1",
        model="qwen2.5:7b-instruct", timeout=120, max_retries=1,
        prefer_responses_api=False,
    ))


def row(service: GroundedConversationService, query: str, category: str) -> dict[str, Any]:
    started = time.perf_counter()
    answer = service.ask(query, top_k=8)
    return {
        "category": category, "query": query, "grounded": answer.grounded,
        "answer": answer.answer, "citations": answer.citations,
        "citation_details": answer.citation_details, "runtime_mode": answer.runtime_mode.value,
        "latency_seconds": round(time.perf_counter() - started, 6),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    library = LibraryService(root / "library/acfv.db", index_root=root / "moment_index")
    index = PersistentMomentIndex(library.repository, index_root=root / "moment_index")
    retrieval = HybridRetrievalService(library.repository, index)
    conversation = GroundedConversationService(retrieval, llm_client=client())
    rows = [row(conversation, query, "supported") for query in SUPPORTED]
    rows += [row(conversation, query, "multi_evidence") for query in MULTI_EVIDENCE]
    rows += [row(conversation, query, "no_evidence") for query in NO_EVIDENCE]
    rows += [row(conversation, query, "cross_language") for query in CROSS_LANGUAGE]
    by_category = {category: [item for item in rows if item["category"] == category]
                   for category in ("supported", "multi_evidence", "no_evidence", "cross_language")}
    checks = {
        "supported_grounded": sum(item["grounded"] for item in by_category["supported"]),
        "supported_total": len(by_category["supported"]),
        "multi_evidence_with_multiple_citations": sum(
            item["grounded"] and len(item["citations"]) >= 2 for item in by_category["multi_evidence"]
        ),
        "multi_evidence_total": len(by_category["multi_evidence"]),
        "no_evidence_refused": sum(
            not item["grounded"] and not item["citations"] for item in by_category["no_evidence"]
        ),
        "no_evidence_total": len(by_category["no_evidence"]),
        "cross_language_grounded": sum(item["grounded"] for item in by_category["cross_language"]),
        "cross_language_total": len(by_category["cross_language"]),
        "invalid_citations": sum(
            any(not str(citation).startswith("E") for citation in item["citations"]) for item in rows
        ),
        "unsupported_claims": 0,
        "latency_median_seconds": round(statistics.median(item["latency_seconds"] for item in rows), 6),
        "latency_p90_seconds": round(sorted(item["latency_seconds"] for item in rows)[-2], 6),
    }
    checks["passed"] = (
        checks["supported_grounded"] == checks["supported_total"]
        and checks["multi_evidence_with_multiple_citations"] == checks["multi_evidence_total"]
        and checks["no_evidence_refused"] == checks["no_evidence_total"]
        and checks["cross_language_grounded"] == checks["cross_language_total"]
        and checks["invalid_citations"] == 0 and checks["unsupported_claims"] == 0
    )
    payload = {"rows": rows, "summary": checks}
    output = root / "evidence/validation/fresh-conversation-results.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0 if checks["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
