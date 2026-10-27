#!/usr/bin/env python3
"""Run fresh retrieval, conversation, clip, language, review and recovery validation."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import time
from typing import Any

from acfv.clips import (
    ClipEventPlan, ClipService, ClipVariantService, DurationProfile, DurationRequest,
    FinalAsrConfig, FinalClipTranscriptService, RenderedVariant, SourceTranscriptRefiner,
    VariantStatus, default_final_translation_provider,
)
from acfv.conversation import GroundedConversationService
from acfv.feedback import FeedbackService
from acfv.library import FeedbackDecision, LibraryService
from acfv.llm.openai_client import OpenAIClientConfig, OpenAIJsonClient
from acfv.moments.models import MomentStatus
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_cross_library_outputs import _duration_units, _row, _source


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _client() -> OpenAIJsonClient:
    return OpenAIJsonClient(OpenAIClientConfig(
        provider="ollama", api_key="ollama", base_url="http://127.0.0.1:11434/v1",
        model="qwen2.5:7b-instruct", timeout=120, max_retries=1,
        prefer_responses_api=False,
    ))


def _activate_cuda_runtime() -> None:
    runtime = Path(sys.prefix) / "Library" / "bin"
    if os.name == "nt" and runtime.is_dir():
        os.environ["PATH"] = str(runtime) + os.pathsep + os.environ.get("PATH", "")
        add = getattr(os, "add_dll_directory", None)
        if callable(add):
            add(str(runtime))


def _query(text: str) -> str:
    tokens = [
        token for token in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", text)
        if token.casefold() not in {"that", "this", "with", "have", "from", "they", "your", "what", "when"}
    ]
    return " ".join(tokens[:6]) or text[:80]


def _plan(db: Path, service: LibraryService, moment_id: str) -> ClipEventPlan:
    item = _row(db, moment_id)
    units, anchor = _duration_units(db, item)
    moment = service.repository.get_moment(moment_id)
    recording = service.get_recording(str(item["recording_id"]))
    creator = service.repository.get_creator(moment.creator_id) if moment else None
    return ClipEventPlan(
        event_id=moment_id, clip_id=moment_id, source_path=str(_source(item)),
        source_duration_ms=int(item["source_duration_ms"]), payoff_anchor_ms=anchor,
        source_language="en", units=tuple(units), words=(), recording_id=str(item["recording_id"]),
        raw_library_transcript=" ".join(unit.text for unit in units),
        event_summary=str(item.get("summary") or item.get("transcript_text") or ""),
        game_title=str(item.get("recording_title") or ""), ocr_context=str(item.get("ocr_text") or ""),
        creator=creator.display_name if creator else "", content_type=recording.content_type if recording else "other",
        current_topic=str(item.get("summary") or item.get("transcript_text") or ""),
    )


def _probe(path: Path, *, decode: bool = False) -> dict[str, Any]:
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration,size",
        "-show_entries", "stream=codec_type,width,height", "-of", "json", str(path),
    ], capture_output=True, text=True, encoding="utf-8", check=False)
    decoded = None
    if decode:
        decoded = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "NUL"],
            capture_output=True,
        ).returncode == 0
    return {"ffprobe": probe.returncode == 0, "metadata": json.loads(probe.stdout or "{}"), "full_decode": decoded}


def evaluate(root: Path, db: Path, index_root: Path) -> list[dict[str, Any]]:
    evidence = root / "evidence" / "validation"
    service = LibraryService(db, index_root=index_root)
    index = PersistentMomentIndex(service.repository, index_root=index_root)
    retrieval = HybridRetrievalService(service.repository, index)
    processing = [row for row in service.list_recordings() if row.source_type == "derived_validation_range"]
    selected: list[dict[str, Any]] = []
    for recording in processing:
        moments = service.repository.list_moments(recording_id=recording.id, status=MomentStatus.FINAL)
        moments.sort(key=lambda item: (len(item.transcript_text), item.end_ms - item.start_ms), reverse=True)
        accepted = []
        for moment in moments:
            if any(abs(moment.start_ms - prior.start_ms) < 25_000 for prior in accepted):
                continue
            plan = _plan(db, service, moment.id)
            boundary = ClipVariantService().select_boundary(plan, DurationRequest(DurationProfile.STANDARD))
            if boundary.status is VariantStatus.READY:
                accepted.append(moment)
            if len(accepted) == 2:
                break
        if len(accepted) != 2:
            raise RuntimeError(f"Need two semantic STANDARD events for {recording.id}; found {len(accepted)}")
        for moment in accepted:
            selected.append({
                "moment_id": moment.id, "recording_id": recording.id,
                "creator_id": recording.creator_id, "content_type": recording.content_type,
                "query": _query(moment.transcript_text), "summary": moment.summary,
            })

    retrieval_rows = []
    latencies = []
    for row in selected:
        started = time.perf_counter()
        hits = retrieval.search(row["query"], top_k=5)
        latency = time.perf_counter() - started
        latencies.append(latency)
        rank = next((index + 1 for index, hit in enumerate(hits) if hit.moment_id == row["moment_id"]), None)
        retrieval_rows.append({**row, "rank": rank, "top5": rank is not None and rank <= 5,
                               "hits": [hit.moment_id for hit in hits], "latency_seconds": latency})
    no_evidence_queries = [
        "quantum pineapple tax treaty on Mars", "underwater violin volcano insurance",
        "火星菠萝税收条约", "海底小提琴火山保险",
    ]
    no_evidence = []
    conversation = GroundedConversationService(retrieval, llm_client=_client())
    for query in no_evidence_queries:
        answer = conversation.ask(query)
        no_evidence.append({"query": query, "grounded": answer.grounded, "answer": answer.answer,
                            "citations": answer.citations, "pass": not answer.grounded and not answer.citations})
    conversation_rows = []
    for row in selected[:6]:
        started = time.perf_counter()
        answer = conversation.ask(row["query"])
        conversation_rows.append({
            "query": row["query"], "grounded": answer.grounded, "answer": answer.answer,
            "citations": answer.citations, "citation_details": answer.citation_details,
            "runtime_mode": answer.runtime_mode.value,
            "latency_seconds": time.perf_counter() - started,
        })

    clips = ClipService(service.repository, output_root=root / "clips")
    for row in selected:
        proposal = clips.create_proposal(row["moment_id"], query=row["query"], relevance_score=1.0)
        row["clip_id"] = proposal.id
        plan = _plan(db, service, row["moment_id"])
        row["duration_profiles"] = [asdict(item) for item in ClipVariantService().duration_service.generate_all(
            event_id=plan.event_id, units=plan.units, payoff_anchor_ms=plan.payoff_anchor_ms,
            source_duration_ms=plan.source_duration_ms,
        )]
    _write(evidence / "fresh-retrieval-fixed-set.json", {"queries": selected, "no_evidence": no_evidence_queries})
    _write(evidence / "fresh-retrieval-results.json", {
        "supported": retrieval_rows,
        "top1": sum(row["rank"] == 1 for row in retrieval_rows) / len(retrieval_rows),
        "top3": sum(bool(row["rank"] and row["rank"] <= 3) for row in retrieval_rows) / len(retrieval_rows),
        "top5": sum(row["top5"] for row in retrieval_rows) / len(retrieval_rows),
        "no_evidence": no_evidence,
        "no_evidence_accuracy": sum(row["pass"] for row in no_evidence) / len(no_evidence),
        "latency_median_seconds": statistics.median(latencies),
        "runtime": retrieval.runtime_metadata(),
    })
    _write(evidence / "fresh-conversation-results.json", {"rows": conversation_rows})
    _write(evidence / "fresh-clip-selection.json", {"events": selected})
    return selected


def render(root: Path, db: Path, index_root: Path) -> list[dict[str, Any]]:
    _activate_cuda_runtime()
    evidence = root / "evidence" / "validation"
    selected = json.loads((evidence / "fresh-clip-selection.json").read_text(encoding="utf-8"))["events"]
    service = LibraryService(db, index_root=index_root)
    client = _client()
    transcript = FinalClipTranscriptService(
        config=FinalAsrConfig(model="large-v3", multilingual_model="large-v3", device="cuda"),
        refiner=SourceTranscriptRefiner(client),
    )
    variants = ClipVariantService(transcript_service=transcript)
    provider = default_final_translation_provider()
    rows = []
    for index, row in enumerate(selected, 1):
        plan = _plan(db, service, row["moment_id"])
        event_root = root / "final-clips" / f"{index:02d}-{row['moment_id'][:8]}"
        started = time.perf_counter()
        generated = (
            variants.generate_all(plan, output_root=event_root, provider=provider)
            if index <= 4 else
            [variants.generate_one(plan, DurationRequest(DurationProfile.STANDARD),
                                   output_root=event_root, provider=provider)]
        )
        for item in generated:
            boundary = item.boundary if isinstance(item, RenderedVariant) else item
            output = Path(item.bilingual_path) if isinstance(item, RenderedVariant) else None
            rows.append({
                **row, "profile": boundary.profile.value, "status": boundary.status.value,
                "start_ms": boundary.start_ms, "end_ms": boundary.end_ms,
                "duration_ms": boundary.duration_ms, "reason": boundary.extension_reason,
                "output": str(output) if output else None,
                "probe": _probe(output, decode=boundary.profile is DurationProfile.STANDARD) if output else None,
                "elapsed_seconds": time.perf_counter() - started,
            })
        standard = next((item for item in generated if isinstance(item, RenderedVariant)
                         and item.boundary.profile is DurationProfile.STANDARD), None)
        if standard is None:
            raise RuntimeError(f"STANDARD render unavailable for {row['moment_id']}")
        shutil.copy2(standard.bilingual_path, event_root / "FINAL_STANDARD.mp4")
        print(f"rendered {index}/{len(selected)} {row['moment_id']}", flush=True)
    standards = [row for row in rows if row["profile"] == "STANDARD" and row["status"] == "READY"]
    _write(evidence / "fresh-clip-results.json", {"events": selected, "variants": rows,
                                                   "standard_ready": len(standards)})
    return rows


def review(root: Path, db: Path, index_root: Path) -> dict[str, Any]:
    evidence = root / "evidence" / "validation"
    service = LibraryService(db, index_root=index_root)
    selected = json.loads((evidence / "fresh-clip-selection.json").read_text(encoding="utf-8"))["events"]
    feedback = FeedbackService(service.repository)
    decisions = []
    existing_feedback = {item.clip_id: item for item in feedback.list_feedback()}
    for index, row in enumerate(selected[:4]):
        decision = FeedbackDecision.ACCEPTED if index < 2 else FeedbackDecision.REJECTED
        saved = existing_feedback.get(row["clip_id"])
        if saved is None:
            saved = feedback.decide(
                row["clip_id"], decision, reason=f"fresh validation {decision.value.lower()}"
            )
        decisions.append(saved.model_dump(mode="json"))
    creator_ids = list(dict.fromkeys(row["creator_id"] for row in selected))
    def preference(text: str, creator_id: str):
        existing = next((item for item in feedback.list_preferences(creator_id)
                         if item.source == "USER_EXPLICIT" and item.text == text), None)
        return existing or feedback.add_preference(text, creator_id=creator_id)

    preferences = [preference("prefer complete reaction", creator_ids[0])]
    if len(creator_ids) > 1:
        preferences.append(preference("prefer complete argument", creator_ids[1]))
    first_recording = selected[0]["recording_id"]
    scoped = feedback.translation_preferences(
        creator_id=selected[0]["creator_id"], recording_scope=first_recording
    )
    if scoped.get("jump scare") != "跳脸惊吓":
        preferences.append(feedback.add_translation_preference(
            "jump scare", "跳脸惊吓", creator_id=selected[0]["creator_id"],
            recording_scope=first_recording,
        ))
    else:
        preferences.append(next(
            item for item in feedback.list_preferences(selected[0]["creator_id"])
            if item.source == "USER_EXPLICIT_TRANSLATION_PREFERENCE"
            and "jump scare" in item.text and first_recording in item.text
        ))
    # Reopen in a new service instance to prove durable state and fresh-index recovery.
    reopened = LibraryService(db, index_root=index_root)
    reopened_index = PersistentMomentIndex(reopened.repository, index_root=index_root)
    payload = {
        "decisions": decisions, "preferences": [item.model_dump(mode="json") for item in preferences],
        "persisted_feedback": len(FeedbackService(reopened.repository).list_feedback()),
        "persisted_preferences": len({
            item.id for creator_id in creator_ids
            for item in FeedbackService(reopened.repository).list_preferences(creator_id)
        }),
        "reopened_index_rows": len(reopened_index.rows()),
        "reopened_recordings": len(reopened.list_recordings()),
    }
    _write(evidence / "fresh-review-feedback-restart.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--phase", choices=("evaluate", "render", "review", "all"), default="all")
    args = parser.parse_args()
    root = args.root.resolve()
    db = root / "library" / "acfv.db"
    index_root = root / "moment_index"
    if args.phase in {"evaluate", "all"}:
        evaluate(root, db, index_root)
    if args.phase in {"render", "all"}:
        render(root, db, index_root)
    if args.phase in {"review", "all"}:
        review(root, db, index_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
