from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from acfv.clips import ClipCandidateSelector
from acfv.conversation import GroundedConversationService
from acfv.library import LibraryService
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex
from acfv.retrieval.query import SearchScope


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a frozen target-content retrieval/conversation set")
    parser.add_argument("--fixed-set", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--index-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    fixed = json.loads(args.fixed_set.read_text(encoding="utf-8"))
    recording_id = fixed["recording_id"]
    library = LibraryService(args.database)
    index = PersistentMomentIndex(library.repository, args.index_root)
    retrieval = HybridRetrievalService(library.repository, index)
    selector = ClipCandidateSelector(library.repository)
    retrieval_rows = []
    for case in fixed["retrieval_queries"]:
        started = time.monotonic()
        results = retrieval.search(case["query"], top_k=10, scope=SearchScope.RECORDING, recording_id=recording_id)
        ids = [item.moment_id for item in results]
        expected = set(case["expected"])
        ranks = [ids.index(item) + 1 for item in expected if item in ids]
        watchability = None
        if expected:
            try:
                candidates = selector.generate(case["query"], results)
                watchability = next(item.watchability.total for item in candidates if item.selected)
            except ValueError:
                watchability = None
        retrieval_rows.append({
            **case,
            "top1": bool(ranks and min(ranks) <= 1),
            "top3": bool(ranks and min(ranks) <= 3),
            "top5": bool(ranks and min(ranks) <= 5),
            "best_rank": min(ranks) if ranks else None,
            "winning_representation": results[0].debug.get("winning_representation_type") if results else None,
            "top_result_moment_id": results[0].moment_id if results else None,
            "selected_watchability": watchability,
            "latency_ms": round((time.monotonic() - started) * 1000, 2),
        })

    conversation = GroundedConversationService(retrieval, llm_client=None)
    conversation_rows = []
    for case in fixed["conversation_queries"]:
        answer = conversation.ask(case["query"], scope=SearchScope.RECORDING, recording_id=recording_id)
        has_evidence = bool(answer.evidence_cards)
        conversation_rows.append({
            **case,
            "answer": answer.answer,
            "runtime_mode": answer.runtime_mode.value,
            "grounded": answer.grounded,
            "has_evidence": has_evidence,
            "correct_gate": has_evidence == bool(case["expect_evidence"]),
            "citations": answer.citations,
            "evidence_moment_ids": [item.moment_id for item in answer.evidence_cards],
        })

    positives = [row for row in retrieval_rows if row["expected"]]
    negatives = [row for row in retrieval_rows if not row["expected"]]
    payload = {
        "schema_version": "1.0",
        "fixed_set": str(args.fixed_set),
        "recording_id": recording_id,
        "runtime": retrieval.runtime_metadata(),
        "retrieval": {
            "cases": retrieval_rows,
            "metrics": {
                "positive_count": len(positives),
                "top1": sum(row["top1"] for row in positives),
                "top3": sum(row["top3"] for row in positives),
                "top5": sum(row["top5"] for row in positives),
                "no_evidence_cases": len(negatives),
            },
        },
        "conversation": {
            "cases": conversation_rows,
            "metrics": {
                "correct_gate": sum(row["correct_gate"] for row in conversation_rows),
                "total": len(conversation_rows),
                "no_evidence_correct": sum(row["correct_gate"] for row in conversation_rows if not row["expect_evidence"]),
                "no_evidence_total": sum(not row["expect_evidence"] for row in conversation_rows),
            },
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"retrieval": payload["retrieval"]["metrics"], "conversation": payload["conversation"]["metrics"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
