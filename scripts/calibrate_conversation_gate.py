"""Capture supported/no-evidence score distributions for a fixed conversation set."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from acfv.library import LibraryService
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex


def terms(text: str) -> set[str]:
    return {item for item in re.findall(r"[\w\u3400-\u9fff]+", text.casefold()) if len(item) > 2}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--index-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    library = LibraryService(args.database)
    retrieval = HybridRetrievalService(library.repository, PersistentMomentIndex(library.repository, args.index_root))
    rows = []
    for case in json.loads(args.cases.read_text(encoding="utf-8")):
        query_terms = terms(case["question"])
        results = retrieval.search(case["question"], top_k=5, candidate_k=50)
        candidates = []
        for rank, result in enumerate(results, 1):
            evidence_terms = terms(result.summary + " " + result.transcript_excerpt)
            candidates.append({
                "rank": rank, "moment_id": result.moment_id,
                "reranker_score": result.debug.get("reranker_score"),
                "dense_score": result.debug.get("dense_score"),
                "shared_terms": sorted(query_terms & evidence_terms),
                "lexical_ratio": len(query_terms & evidence_terms) / max(1, len(query_terms)),
                "excerpt": result.transcript_excerpt[:300],
            })
        rows.append({"case_id": case["case_id"], "evaluation_type": case["evaluation_type"], "question": case["question"], "candidates": candidates})
        print(case["case_id"], case["evaluation_type"], candidates[0] if candidates else None, flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    library.repository.engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
