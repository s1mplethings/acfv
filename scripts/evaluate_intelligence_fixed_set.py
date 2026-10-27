"""Run the immutable 20261008 intelligence evaluation against a rebuilt Library."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import statistics
import subprocess
import time
import zipfile
from pathlib import Path

from acfv.clips import ClipService
from acfv.conversation import GroundedConversationService
from acfv.library import LibraryService
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def overlap(left_start, left_end, right_start, right_end):
    return max(0, min(left_end, right_end) - max(left_start, right_start))


def resolve_anchor(repository, recording_id, start_ms, end_ms, transcript_anchor, fallback_id):
    candidates = [
        item for item in repository.list_moments(recording_id=recording_id)
        if overlap(start_ms, end_ms, item.start_ms, item.end_ms) > 0
    ]
    if not candidates:
        return repository.get_moment(fallback_id)
    anchor_terms = set(re.findall(r"[\w\u3400-\u9fff]+", transcript_anchor.casefold()))
    def score(item):
        terms = set(re.findall(r"[\w\u3400-\u9fff]+", item.transcript_text.casefold()))
        lexical_recall = len(anchor_terms & terms) / max(1, len(anchor_terms))
        temporal = overlap(start_ms, end_ms, item.start_ms, item.end_ms) / max(1, end_ms - start_ms)
        return lexical_recall, temporal, -abs(start_ms - item.start_ms)
    return max(candidates, key=score)


def anchor_children(repository, recording_id, start_ms, end_ms):
    return [
        item for item in repository.list_moments(recording_id=recording_id)
        if overlap(start_ms, end_ms, item.start_ms, item.end_ms) > 0
    ]


def result_dict(item, rank):
    return {
        "rank": rank,
        "moment_id": item.moment_id,
        "recording_id": item.recording_id,
        "recording_title": item.recording_title,
        "start_ms": item.start_ms,
        "end_ms": item.end_ms,
        "score": item.score,
        "summary": item.summary,
        "transcript_excerpt": item.transcript_excerpt,
        "debug": item.debug,
    }


def metric(ranks, limit):
    return sum(rank is not None and rank <= limit for rank in ranks)


def evaluate_retrieval(cases, retrieval, repository, mapping):
    rows, latencies, ranks = [], [], []
    for number, case in enumerate(cases, 1):
        started = time.perf_counter()
        results = retrieval.search(case["query"], top_k=30, candidate_k=50)
        latency = (time.perf_counter() - started) * 1000
        truth = case["ground_truth"]
        target_moment = resolve_anchor(
            repository, truth["recording_id"], truth["start_ms"], truth["end_ms"],
            truth["transcript_excerpt"], mapping[truth["moment_id"]],
        )
        acceptable = {item.id for item in anchor_children(repository, truth["recording_id"], truth["start_ms"], truth["end_ms"])}
        ids = [item.moment_id for item in results]
        matching_ranks = [rank_ for rank_, identity in enumerate(ids, 1) if identity in acceptable]
        rank = min(matching_ranks) if matching_ranks else None
        target = ids[rank - 1] if rank else target_moment.id
        ranks.append(rank)
        latencies.append(latency)
        row = {
            "case_id": case["case_id"],
            "category": case["category"],
            "language_style": case["language_style"],
            "query": case["query"],
            "ground_truth": {**case["ground_truth"], "old_moment_id": case["ground_truth"]["moment_id"], "moment_id": target, "acceptable_child_ids": sorted(acceptable)},
            "target_rank": rank,
            "latency_ms": round(latency, 3),
            "target_diagnostics": next((item.debug for item in results if item.moment_id == target), {}),
            "top30": [result_dict(item, rank_) for rank_, item in enumerate(results, 1)],
        }
        rows.append(row)
        print(f"retrieval {number:02d}/20 {case['case_id']} rank={rank}", flush=True)
    metrics = {
        "top1": metric(ranks, 1), "top3": metric(ranks, 3), "top5": metric(ranks, 5),
        "top10": metric(ranks, 10), "top30": metric(ranks, 30),
        "mrr": sum(1 / rank for rank in ranks if rank) / len(ranks),
        "median_latency_ms": statistics.median(latencies),
        "p90_latency_ms": sorted(latencies)[max(0, int(len(latencies) * 0.9) - 1)],
    }
    return rows, metrics


def evaluate_moments(cases, repository, mapping):
    rows = []
    for case in cases:
        old_id = case["moment_id"]
        moment = resolve_anchor(
            repository, case["recording_id"], case["start_ms"], case["end_ms"],
            case["moment_transcript"], mapping[old_id],
        )
        duration = moment.end_ms - moment.start_ms
        punctuation = not any(char.isalnum() for char in moment.transcript_text)
        tokens = {token for token in moment.transcript_text.casefold().split() if any(char.isalnum() for char in token)}
        low_info = len(tokens) <= 1 and len("".join(char for char in moment.transcript_text if char.isalnum())) < 8
        summary_copy = " ".join(moment.summary.split()).casefold() == " ".join(moment.transcript_text.split()).casefold()
        reasons = []
        if punctuation: reasons.append("punctuation_only")
        if low_info: reasons.append("single_token_low_info")
        if duration < 5_000: reasons.append("unusually_short")
        if summary_copy and len(moment.transcript_text) > 240: reasons.append("summary_copies_long_transcript")
        rows.append({
            **case,
            "old_moment_id": old_id,
            "moment_id": moment.id,
            "old_start_ms": case["start_ms"], "old_end_ms": case["end_ms"],
            "start_ms": moment.start_ms, "end_ms": moment.end_ms, "duration_ms": duration,
            "old_summary": case["summary"], "summary": moment.summary,
            "old_transcript": case["moment_transcript"], "moment_transcript": moment.transcript_text,
            "anchor_overlap_ms": overlap(case["start_ms"], case["end_ms"], moment.start_ms, moment.end_ms),
            "automatic_result": "AUTO_SUSPECT" if reasons else "AUTO_PASS",
            "suspect_reasons": reasons,
        })
    metrics = {
        "punctuation_only": sum("punctuation_only" in row["suspect_reasons"] for row in rows),
        "low_info_suspects": sum("single_token_low_info" in row["suspect_reasons"] for row in rows),
        "near_60_seconds": sum(50_000 <= row["duration_ms"] < 60_000 for row in rows),
        "ge_50_seconds": sum(row["duration_ms"] >= 50_000 for row in rows),
        "ge_55_seconds": sum(row["duration_ms"] >= 55_000 for row in rows),
        "auto_suspect": sum(row["automatic_result"] == "AUTO_SUSPECT" for row in rows),
        "summary_copy": sum(" ".join(row["summary"].split()).casefold() == " ".join(row["moment_transcript"].split()).casefold() for row in rows),
    }
    return rows, metrics


def evaluate_conversation(cases, conversation):
    rows = []
    for number, case in enumerate(cases, 1):
        started = time.perf_counter()
        answer = conversation.ask(case["question"])
        elapsed = (time.perf_counter() - started) * 1000
        rows.append({
            "case_id": case["case_id"], "evaluation_type": case["evaluation_type"], "question": case["question"],
            "assistant_answer": answer.answer, "grounded": answer.grounded, "confidence": answer.confidence,
            "runtime_mode": answer.runtime_mode.value, "citations": answer.citations,
            "citation_details": answer.citation_details or [], "latency_ms": round(elapsed, 3),
            "retrieved_evidence": [result_dict(item, rank) for rank, item in enumerate(answer.evidence_cards, 1)],
        })
        print(f"conversation {number:02d}/15 {case['case_id']} mode={answer.runtime_mode.value} evidence={len(answer.evidence_cards)}", flush=True)
    no_evidence = [row for row in rows if row["evaluation_type"] == "NO_EVIDENCE"]
    metrics = {
        "correct_no_evidence_rejects": sum(not row["retrieved_evidence"] and not row["grounded"] for row in no_evidence),
        "invalid_citations": sum(
            any(citation not in ({item["moment_id"] for item in row["retrieved_evidence"]} | {item.get("evidence_id") for item in row["citation_details"]}) for citation in row["citations"])
            for row in rows
        ),
        "unsupported_claims": sum(bool(row["assistant_answer"].strip()) and row["grounded"] and not row["citations"] for row in rows),
        "multi_evidence_coverage": sum(len({item["recording_id"] for item in row["retrieved_evidence"]}) >= 2 for row in rows if row["evaluation_type"] == "MULTI_EVIDENCE"),
        "median_latency_ms": statistics.median(row["latency_ms"] for row in rows),
    }
    return rows, metrics


def ffprobe(path: Path, expected_ms: int):
    command = ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-show_entries", "format=duration", "-of", "json", str(path)]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    payload = json.loads(completed.stdout or "{}") if completed.returncode == 0 else {}
    types = {stream.get("codec_type") for stream in payload.get("streams", [])}
    duration = float(payload.get("format", {}).get("duration") or 0)
    return {
        "returncode": completed.returncode, "video": "video" in types, "audio": "audio" in types,
        "duration_seconds": duration, "size_bytes": path.stat().st_size if path.is_file() else 0,
        "duration_matches_proposal": abs(duration * 1000 - expected_ms) <= 1500,
        "pass": completed.returncode == 0 and {"video", "audio"}.issubset(types) and abs(duration * 1000 - expected_ms) <= 1500,
    }


def evaluate_clips(cases, repository, mapping, retrieval, output):
    service = ClipService(repository, output_root=output / "clips" / "render_work")
    media = output / "clips" / "clips_after"
    media.mkdir(parents=True, exist_ok=True)
    rows = []
    for number, case in enumerate(cases, 1):
        moment = resolve_anchor(
            repository, case["source_recording_id"], case["moment_start_ms"], case["moment_end_ms"],
            case.get("context_20s", {}).get("inside", ""), mapping[case["moment_id"]],
        )
        query = case.get("query") or ""
        relevance_score = None
        target_rank = None
        if query:
            hits = retrieval.search(query, top_k=30, candidate_k=50)
            target = next((item for item in hits if item.moment_id == moment.id), None)
            target_rank = next((rank for rank, item in enumerate(hits, 1) if item.moment_id == moment.id), None)
            relevance_score = target.score if target else None
        rejected = None
        rendered_path = None
        proposal = None
        destination = media / f"clip_{number:02d}.mp4"
        try:
            if query and target_rank is None:
                raise ValueError("Insufficient retrieval evidence for a confident Clip proposal")
            proposal = service.create_proposal(
                moment.id, query=query, relevance_score=relevance_score,
                minimum_relevance_score=-7.0 if relevance_score is not None else 0.0,
            )
            proposal = service.update_review(proposal.id, subtitle_text=moment.transcript_text)
            if not destination.is_file():
                rendered = service.render(proposal.id)
                Path(rendered.output_path).replace(destination)
            rendered_path = destination.resolve()
        except ValueError as exc:
            rejected = str(exc)
        reasons = json.loads(proposal.reason) if proposal else {}
        checks = ffprobe(rendered_path, proposal.final_end_ms - proposal.final_start_ms) if rendered_path else None
        suspect = []
        if rejected: suspect.append("rejected_low_confidence_or_value")
        if proposal and reasons.get("start_reason") == "fixed_context_fallback": suspect.append("starts_mid_sentence")
        if proposal and reasons.get("end_reason") == "fixed_context_fallback": suspect.append("ends_mid_sentence")
        rows.append({
            "case_id": case["case_id"], "group": case["group"], "query": query,
            "old_moment_id": case["moment_id"], "moment_id": moment.id, "source_recording_id": moment.recording_id,
            "old_moment_start_ms": case["moment_start_ms"], "old_moment_end_ms": case["moment_end_ms"],
            "moment_start_ms": moment.start_ms, "moment_end_ms": moment.end_ms,
            "retrieval_target_rank": target_rank, "retrieval_score": relevance_score,
            "rejected_reason": rejected,
            "proposed_start_ms": proposal.proposed_start_ms if proposal else None,
            "proposed_end_ms": proposal.proposed_end_ms if proposal else None,
            "chosen_start_reason": reasons.get("start_reason"), "chosen_end_reason": reasons.get("end_reason"),
            "file": str(rendered_path.relative_to(output.resolve())) if rendered_path else None,
            "automated_checks": {"ffprobe": checks} if checks else {},
            "automatic_result": "AUTO_SUSPECT" if suspect else "AUTO_PASS", "suspect_reasons": suspect,
        })
        print(f"clip {number:02d}/15 {case['case_id']} {'rejected' if rejected else 'rendered'}", flush=True)
    metrics = {
        "renders": sum(row["file"] is not None for row in rows),
        "ffprobe_pass": sum((row["automated_checks"].get("ffprobe") or {}).get("pass", False) for row in rows),
        "query_mismatch_rejected": sum(bool(row["query"]) and row["rejected_reason"] is not None for row in rows),
        "mid_start": sum("starts_mid_sentence" in row["suspect_reasons"] for row in rows),
        "mid_end": sum("ends_mid_sentence" in row["suspect_reasons"] for row in rows),
        "low_value_rejected": sum(row["rejected_reason"] is not None for row in rows),
        "auto_suspect": sum(row["automatic_result"] == "AUTO_SUSPECT" for row in rows),
    }
    return rows, metrics


def holdout(repository, retrieval, seed=20261009):
    rng = random.Random(seed)
    moments = repository.list_moments()
    chosen = rng.sample(moments, 20)
    retrieval_rows = []
    for moment in chosen[:10]:
        query = " ".join(moment.transcript_text.split()[:12])
        hits = retrieval.search(query, top_k=10, candidate_k=30)
        ids = [item.moment_id for item in hits]
        retrieval_rows.append({"moment_id": moment.id, "query": query, "rank": ids.index(moment.id) + 1 if moment.id in ids else None})
    clip_service = ClipService(repository)
    clip_rows = []
    for moment in chosen[10:15]:
        try:
            proposal = clip_service.create_proposal(moment.id)
            clip_rows.append({"moment_id": moment.id, "eligible": True, "start_ms": proposal.proposed_start_ms, "end_ms": proposal.proposed_end_ms})
        except ValueError as exc:
            clip_rows.append({"moment_id": moment.id, "eligible": False, "reason": str(exc)})
    return {
        "seed": seed, "retrieval": retrieval_rows,
        "moments": [{"moment_id": item.id, "duration_ms": item.end_ms - item.start_ms, "summary": item.summary} for item in chosen[10:20]],
        "clips": clip_rows,
    }


def zip_bundle(output: Path) -> Path:
    destination = output / "evaluation_bundle_v2.zip"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(output.rglob("*")):
            if path.is_file() and path != destination and "render_work" not in path.parts:
                archive.write(path, path.relative_to(output))
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--index-root", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--implementation-sha", required=True)
    parser.add_argument("--replace-output", action="store_true")
    parser.add_argument("--resume-output", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        if args.replace_output and args.output.name == "product-evaluation-v2":
            shutil.rmtree(args.output)
        elif not args.resume_output:
            raise FileExistsError(f"Refusing to overwrite evaluation output: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)
    mapping_rows = read_json(args.mapping)
    mapping = {row["old_moment_id"]: row["new_moment_id"] for row in mapping_rows}
    library = LibraryService(args.database)
    index = PersistentMomentIndex(library.repository, args.index_root)
    retrieval = HybridRetrievalService(library.repository, index)

    retrieval_rows, retrieval_metrics = evaluate_retrieval(read_json(args.baseline / "retrieval/cases.json"), retrieval, library.repository, mapping)
    write_json(args.output / "retrieval/cases.json", retrieval_rows)
    for row in retrieval_rows: write_json(args.output / "retrieval/raw_results" / f"{row['case_id']}.json", row)
    moment_rows, moment_metrics = evaluate_moments(read_json(args.baseline / "moments/cases.json"), library.repository, mapping)
    write_json(args.output / "moments/cases.json", moment_rows)
    conversation = GroundedConversationService(retrieval, llm_client=None)
    conversation_rows, conversation_metrics = evaluate_conversation(read_json(args.baseline / "conversation/cases.json"), conversation)
    write_json(args.output / "conversation/cases.json", conversation_rows)
    clips_before = args.output / "clips" / "clips_before"
    clips_before.mkdir(parents=True, exist_ok=True)
    for source in sorted((args.baseline / "clips" / "media").glob("*.mp4")):
        shutil.copy2(source, clips_before / source.name)
    clip_rows, clip_metrics = evaluate_clips(read_json(args.baseline / "clips/cases.json"), library.repository, mapping, retrieval, args.output)
    write_json(args.output / "clips/cases.json", clip_rows)
    holdout_rows = holdout(library.repository, retrieval)
    write_json(args.output / "holdout/cases.json", holdout_rows)
    metrics = {"retrieval": retrieval_metrics, "moments": moment_metrics, "conversation": conversation_metrics, "clips": clip_metrics}
    baseline_sha = hashlib.sha256((args.baseline / "evaluation_bundle.zip").read_bytes()).hexdigest()
    metadata = {
        "evaluation_version": "2.0.0", "implementation_sha": args.implementation_sha,
        "seed": 20261008, "holdout_seed": 20261009,
        "fixed_case_ids": {
            "retrieval": [row["case_id"] for row in retrieval_rows], "moments": [row["case_id"] for row in moment_rows],
            "conversation": [row["case_id"] for row in conversation_rows], "clips": [row["case_id"] for row in clip_rows],
        },
        "baseline_sha256": baseline_sha, "library": {"recordings": 10, "hours": 52.43064361111111, "final_moments": len(library.repository.list_moments()), "index_rows": len(index.rows())},
        "runtime": {**retrieval.runtime_metadata(), "conversation_mode": "EVIDENCE_ONLY"}, "metrics": metrics,
    }
    write_json(args.output / "metadata.json", metadata)
    comparison = ["# ACFV Intelligence Quality Comparison", "", "Metric | Baseline | V2 | Delta", "---|---:|---:|---:"]
    baseline_values = {"Retrieval Top5": 0, "Retrieval Top10": 0, "Moment punctuation-only (fixed 30)": 0, "Moment AUTO_SUSPECT": 4, "Conversation no-evidence correct": 3, "Clip ffprobe pass": 15, "Clip AUTO_SUSPECT": 9}
    v2_values = {"Retrieval Top5": retrieval_metrics["top5"], "Retrieval Top10": retrieval_metrics["top10"], "Moment punctuation-only (fixed 30)": moment_metrics["punctuation_only"], "Moment AUTO_SUSPECT": moment_metrics["auto_suspect"], "Conversation no-evidence correct": conversation_metrics["correct_no_evidence_rejects"], "Clip ffprobe pass": clip_metrics["ffprobe_pass"], "Clip AUTO_SUSPECT": clip_metrics["auto_suspect"]}
    for key, baseline_value in baseline_values.items(): comparison.append(f"{key} | {baseline_value} | {v2_values[key]} | {v2_values[key] - baseline_value:+}")
    (args.output / "comparison.md").write_text("\n".join(comparison) + "\n", encoding="utf-8")
    (args.output / "challenge_cases.md").write_text((args.baseline / "challenge_cases.md").read_text(encoding="utf-8"), encoding="utf-8")
    bundle = zip_bundle(args.output)
    metadata["bundle"] = {"path": str(bundle.resolve()), "size_bytes": bundle.stat().st_size, "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest()}
    write_json(args.output / "product-evaluation-v2-receipt.json", metadata)
    print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)
    library.repository.engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
