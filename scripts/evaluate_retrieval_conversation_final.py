"""Build the immutable V3 evaluation bundle for retrieval/conversation finalization."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate_intelligence_fixed_set as base

from acfv.conversation import GroundedConversationService
from acfv.library import LibraryService
from acfv.llm import OpenAIClientConfig, OpenAIJsonClient
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def evaluate_clips_without_retranscode(baseline_cases, v2_rows, repository, mapping, retrieval, output: Path, v2_root: Path):
    prior = {row["case_id"]: row for row in v2_rows}
    media_dir = output / "clips" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for number, case in enumerate(baseline_cases, 1):
        old_id = case["moment_id"]
        moment = base.resolve_anchor(repository, case["source_recording_id"], case["moment_start_ms"], case["moment_end_ms"], case.get("context_20s", {}).get("inside", ""), mapping[old_id])
        query = case.get("query") or ""
        hits = retrieval.search(query, top_k=30, candidate_k=50) if query else []
        target = next((item for item in hits if item.moment_id == moment.id), None)
        rank = next((rank for rank, item in enumerate(hits, 1) if item.moment_id == moment.id), None)
        old = prior[case["case_id"]]
        source = v2_root / "clips" / "clips_after" / f"clip_{number:02d}.mp4"
        copied = None
        checks = None
        if source.is_file() and old.get("proposed_start_ms") is not None:
            copied = media_dir / source.name
            shutil.copy2(source, copied)
            expected = int(old["proposed_end_ms"]) - int(old["proposed_start_ms"])
            checks = base.ffprobe(copied, expected)
        expected_rejection = bool(query and rank is None)
        rendered_suspect = []
        if copied and not (checks or {}).get("pass"):
            rendered_suspect.append("ffprobe_failed")
        if copied and old.get("chosen_start_reason") == "fixed_context_fallback":
            rendered_suspect.append("starts_mid_sentence")
        if copied and old.get("chosen_end_reason") == "fixed_context_fallback":
            rendered_suspect.append("ends_mid_sentence")
        rows.append({
            **case,
            "old_moment_id": old_id,
            "moment_id": moment.id,
            "retrieval_target_rank": rank,
            "retrieval_score": target.score if target else None,
            "expected_bad_source_rejected": expected_rejection,
            "rejected_reason": "Insufficient retrieval evidence for a confident Clip proposal" if expected_rejection else None,
            "proposed_start_ms": old.get("proposed_start_ms"), "proposed_end_ms": old.get("proposed_end_ms"),
            "chosen_start_reason": old.get("chosen_start_reason"), "chosen_end_reason": old.get("chosen_end_reason"),
            "file": str(copied.relative_to(output)) if copied else None,
            "automated_checks": {"ffprobe": checks} if checks else {},
            "automatic_result": "AUTO_SUSPECT" if rendered_suspect else ("AUTO_REJECTED_EXPECTED" if expected_rejection else "AUTO_PASS"),
            "suspect_reasons": rendered_suspect,
        })
    metrics = {
        "renders": sum(row["file"] is not None for row in rows),
        "ffprobe_pass": sum((row["automated_checks"].get("ffprobe") or {}).get("pass", False) for row in rows),
        "bad_retrieval_sources_rejected": sum(row["expected_bad_source_rejected"] for row in rows),
        "mid_start": sum("starts_mid_sentence" in row["suspect_reasons"] for row in rows),
        "mid_end": sum("ends_mid_sentence" in row["suspect_reasons"] for row in rows),
        "rendered_auto_suspect": sum(row["file"] is not None and row["automatic_result"] == "AUTO_SUSPECT" for row in rows),
    }
    return rows, metrics


def review_markdown(title: str, rows: list[dict], fields: list[str]) -> str:
    lines = [f"# {title}", "", "Human review status: PENDING (automated evidence prepared; no human verdict invented).", ""]
    for row in rows:
        lines.append(f"## {row.get('case_id')}")
        for field in fields:
            lines.append(f"- {field}: {row.get(field)}")
        lines.extend(["- Human rating: PENDING", "- Human notes:", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--v2", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--index-root", type=Path, required=True)
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--implementation-sha", required=True)
    parser.add_argument("--replace-output", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        if args.replace_output and args.output.name == "product-evaluation-v3":
            shutil.rmtree(args.output)
        else:
            raise FileExistsError(f"Refusing to overwrite {args.output}")
    args.output.mkdir(parents=True)
    v2_retrieval = base.read_json(args.v2 / "retrieval/cases.json")
    v2_moments = base.read_json(args.v2 / "moments/cases.json")
    v2_clips = base.read_json(args.v2 / "clips/cases.json")
    mapping = {}
    mapping.update({row["ground_truth"].get("old_moment_id", row["ground_truth"]["moment_id"]): row["ground_truth"]["moment_id"] for row in v2_retrieval})
    mapping.update({row.get("old_moment_id", row["moment_id"]): row["moment_id"] for row in v2_moments})
    mapping.update({row.get("old_moment_id", row["moment_id"]): row["moment_id"] for row in v2_clips})
    library = LibraryService(args.database)
    index = PersistentMomentIndex(library.repository, args.index_root)
    retrieval = HybridRetrievalService(library.repository, index)
    retrieval_rows, retrieval_metrics = base.evaluate_retrieval(base.read_json(args.baseline / "retrieval/cases.json"), retrieval, library.repository, mapping)
    write_json(args.output / "retrieval/cases.json", retrieval_rows)
    for row in retrieval_rows:
        write_json(args.output / "retrieval/raw_results" / f"{row['case_id']}.json", row)
    shutil.copy2(args.diagnostics, args.output / "retrieval" / "representation_diagnostics.json")
    moment_rows, moment_metrics = base.evaluate_moments(base.read_json(args.baseline / "moments/cases.json"), library.repository, mapping)
    write_json(args.output / "moments/cases.json", moment_rows)
    conversation_client = OpenAIJsonClient(OpenAIClientConfig(
        provider="ollama", api_key="ollama", base_url="http://127.0.0.1:11434/v1",
        model="qwen2.5:7b-instruct", timeout=60.0, max_retries=0, prefer_responses_api=False,
    ))
    conversation = GroundedConversationService(retrieval, llm_client=conversation_client)
    conversation_rows, conversation_metrics = base.evaluate_conversation(base.read_json(args.baseline / "conversation/cases.json"), conversation)
    write_json(args.output / "conversation/cases.json", conversation_rows)
    clip_rows, clip_metrics = evaluate_clips_without_retranscode(base.read_json(args.baseline / "clips/cases.json"), v2_clips, library.repository, mapping, retrieval, args.output, args.v2)
    write_json(args.output / "clips/cases.json", clip_rows)
    holdout_rows = base.holdout(library.repository, retrieval)
    write_json(args.output / "holdout/cases.json", holdout_rows)
    shutil.copy2(args.baseline / "challenge_cases.md", args.output / "challenge_cases.md")
    (args.output / "retrieval/review.md").write_text(review_markdown("V3 Retrieval Human Review", retrieval_rows, ["query", "target_rank", "latency_ms"]), encoding="utf-8")
    (args.output / "conversation/review.md").write_text(review_markdown("V3 Conversation Human Review", conversation_rows, ["question", "assistant_answer", "runtime_mode", "citations"]), encoding="utf-8")
    (args.output / "moments/review.md").write_text(review_markdown("V3 Moment Regression Review", moment_rows, ["summary", "automatic_result", "suspect_reasons"]), encoding="utf-8")
    (args.output / "clips/review.md").write_text(review_markdown("V3 Clip Regression Review", clip_rows, ["query", "retrieval_target_rank", "automatic_result", "file"]), encoding="utf-8")
    metrics = {"retrieval": retrieval_metrics, "conversation": conversation_metrics, "moments": moment_metrics, "clips": clip_metrics}
    metadata = {
        "evaluation_version": "3.0.0", "implementation_sha": args.implementation_sha,
        "seed": 20261008, "holdout_seed": 20261009,
        "library": {"recordings": len(library.repository.list_recordings()), "final_moments": len(library.repository.list_moments()), "index_parents": len(index.rows()), "index_representations": len(index.representations())},
        "runtime": {**retrieval.runtime_metadata(), "conversation_provider": "ollama", "conversation_model": "qwen2.5:7b-instruct"},
        "metrics": metrics,
    }
    write_json(args.output / "metadata.json", metadata)
    comparison = ["# V3 Comparison", "", "Metric | V2 | V3 | Delta", "---|---:|---:|---:"]
    v2_meta = base.read_json(args.v2 / "metadata.json")
    for label, path in (("Retrieval Top5", ("retrieval", "top5")), ("Retrieval Top10", ("retrieval", "top10")), ("Conversation no-evidence", ("conversation", "correct_no_evidence_rejects")), ("Moment AUTO_SUSPECT", ("moments", "auto_suspect"))):
        old = v2_meta["metrics"][path[0]][path[1]]
        new = metrics[path[0]][path[1]]
        comparison.append(f"{label} | {old} | {new} | {new-old:+}")
    (args.output / "comparison.md").write_text("\n".join(comparison) + "\n", encoding="utf-8")
    bundle = args.output / "evaluation_bundle_v3.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(args.output.rglob("*")):
            if path.is_file() and path != bundle:
                archive.write(path, path.relative_to(args.output))
    receipt = {**metadata, "bundle": {"path": str(bundle.resolve()), "size_bytes": bundle.stat().st_size, "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest()}}
    write_json(args.output / "product-evaluation-v3-receipt.json", receipt)
    print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
