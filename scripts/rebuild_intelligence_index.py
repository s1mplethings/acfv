"""Rebuild and verify the real semantic Moment index."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from acfv.library import LibraryService
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--index-root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--fts-only", action="store_true")
    args = parser.parse_args()

    library = LibraryService(args.database)
    index = PersistentMomentIndex(library.repository, args.index_root)
    retrieval = HybridRetrievalService(library.repository, index, load_default_reranker=False)
    started = time.perf_counter()
    indexed = retrieval.rebuild_lexical() if args.fts_only else retrieval.rebuild()
    elapsed = time.perf_counter() - started
    final_count = len(library.repository.list_moments())
    rows = len(index.rows())
    if indexed != final_count or rows != final_count:
        raise RuntimeError(f"Index mismatch: FINAL={final_count}, rebuild={indexed}, rows={rows}")
    receipt = {
        "database": str(args.database.resolve()),
        "index_root": str(args.index_root.resolve()),
        "final_moments": final_count,
        "index_rows": rows,
        "elapsed_seconds": round(elapsed, 3),
        "fts_rebuilt": True,
        "runtime": index.runtime_metadata(),
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)
    library.repository.engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
