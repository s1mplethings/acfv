"""Compare multilingual E5 models on the immutable retrieval anchors."""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import numpy as np

from acfv.ragstack.embeddings.encoder import load_encoder
from acfv.retrieval import PersistentMomentIndex
from acfv.library import LibraryService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--index-root", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=2000)
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    library = LibraryService(args.database)
    rows = PersistentMomentIndex(library.repository, args.index_root).representations()
    targets = {case["ground_truth"]["moment_id"] for case in cases}
    target_rows = [row for row in rows if row.parent_moment_id in targets]
    background = [row for row in rows if row.parent_moment_id not in targets]
    sampled = random.Random(20261008).sample(background, min(args.sample_size, len(background))) + target_rows
    texts = [row.text for row in sampled]
    queries = [case["query"] for case in cases]
    cross_language = [
        ("中文到英文", "她为什么说自己饿了？", "She said she was hungry because she had not eaten.", "The spaceship landed on Mars."),
        ("英文到日文", "Please turn this way one more time", "もう一回こっち向いて", "今日は雨が降っています"),
        ("中文到日文", "再朝这边看一次", "もう一回こっち向いて", "猫が窓の外を見ている"),
    ]
    report = {"seed": 20261008, "sample_size": len(sampled), "models": {}}
    for model_name in ("intfloat/multilingual-e5-small", "intfloat/multilingual-e5-base"):
        started = time.perf_counter()
        encoder = load_encoder(model_name)
        corpus = encoder.encode_passages(texts)
        query_vectors = encoder.encode_queries(queries)
        similarities = query_vectors @ corpus.T
        ranks = []
        per_case = []
        for case, scores in zip(cases, similarities):
            order = np.argsort(-scores)
            target_id = case["ground_truth"]["moment_id"]
            rank = next((position for position, index in enumerate(order, 1) if sampled[index].parent_moment_id == target_id), None)
            ranks.append(rank)
            per_case.append({"case_id": case["case_id"], "sample_rank": rank})
        smoke = []
        for name, query, positive, negative in cross_language:
            q = encoder.encode_queries([query])[0]
            p = encoder.encode_passages([positive, negative])
            smoke.append({"name": name, "positive_similarity": float(q @ p[0]), "negative_similarity": float(q @ p[1]), "pass": bool(q @ p[0] > q @ p[1])})
        report["models"][model_name] = {
            "elapsed_sec": time.perf_counter() - started,
            "top5": sum(rank is not None and rank <= 5 for rank in ranks),
            "top10": sum(rank is not None and rank <= 10 for rank in ranks),
            "median_rank": float(np.median([rank for rank in ranks if rank is not None])),
            "cases": per_case,
            "cross_language": smoke,
        }
        print(model_name, report["models"][model_name]["top5"], flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
