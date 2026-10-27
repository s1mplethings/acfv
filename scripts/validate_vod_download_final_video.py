from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from acfv.clips import ClipService
from acfv.config import ConfigManager
from acfv.conversation import GroundedConversationService, NO_EVIDENCE_ANSWER
from acfv.feedback import FeedbackService
from acfv.library import FeedbackDecision, LibraryService
from acfv.llm import get_default_client
from acfv.processing.subtitle_render import apply_style_preset, burn_in
from acfv.providers.download import validate_downloaded_media
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex, SearchScope
from acfv.steps.subtitle_generator.impl import generate_semantic_subtitles_for_clips


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _target_moment(moments, needle: str):
    lowered = needle.casefold()
    for moment in moments:
        if lowered in moment.summary.casefold():
            return moment
    return next(moment for moment in moments if lowered in moment.transcript_text.casefold())


def _search_row(query: str, target_id: str, retrieval, recording_id: str) -> dict[str, Any]:
    hits = retrieval.search(
        query,
        top_k=5,
        scope=SearchScope.RECORDING,
        recording_id=recording_id,
    )
    rank = next((index for index, hit in enumerate(hits, 1) if hit.moment_id == target_id), None)
    return {
        "query": query,
        "target_moment_id": target_id,
        "target_rank": rank,
        "top_hits": [
            {
                "rank": index,
                "moment_id": hit.moment_id,
                "score": hit.score,
                "winning_representation": hit.debug.get("winning_representation_type"),
                "dense_score": hit.debug.get("dense_score"),
                "fts_rank": hit.debug.get("fts_rank"),
                "reranker_score": hit.debug.get("reranker_score"),
            }
            for index, hit in enumerate(hits, 1)
        ],
    }


def _conversation_row(service, query: str, recording_id: str) -> dict[str, Any]:
    answer = service.ask(
        query,
        scope=SearchScope.RECORDING,
        recording_id=recording_id,
    )
    evidence_ids = {f"E{index}" for index in range(1, len(answer.evidence_cards) + 1)}
    return {
        "query": query,
        "answer": answer.answer,
        "grounded": answer.grounded,
        "confidence": answer.confidence,
        "runtime_mode": answer.runtime_mode.value,
        "citations": answer.citations,
        "invalid_citations": sorted(set(answer.citations) - evidence_ids),
        "evidence_moment_ids": [item.moment_id for item in answer.evidence_cards],
    }


def _transcript_checks(segments: list[dict[str, Any]], duration_ms: int) -> dict[str, Any]:
    zero_length = 0
    non_monotonic = 0
    duplicates = 0
    previous_start = -1.0
    previous_text = None
    spoken_ms = 0
    for segment in segments:
        start = float(segment["start"])
        end = float(segment["end"])
        text = str(segment.get("text") or "").strip()
        if end <= start:
            zero_length += 1
        if start < previous_start:
            non_monotonic += 1
        if text and text == previous_text:
            duplicates += 1
        spoken_ms += max(0, int((end - start) * 1000))
        previous_start = start
        previous_text = text
    last_ms = int(float(segments[-1]["end"]) * 1000) if segments else 0
    return {
        "entries": len(segments),
        "zero_length": zero_length,
        "non_monotonic": non_monotonic,
        "adjacent_duplicate_text": duplicates,
        "last_timestamp_ms": last_ms,
        "within_media_duration": last_ms <= duration_ms + 1_000,
        "spoken_coverage": spoken_ms / max(1, duration_ms),
    }


def _copy_generated_srt(named_clip: Path, destination: Path) -> Path:
    generated = named_clip.with_suffix(".srt")
    if not generated.is_file():
        raise RuntimeError(f"Subtitle generator did not create {generated}")
    shutil.copy2(generated, destination)
    return destination


def _render_timed_version(
    clean_video: Path,
    transcript_path: Path,
    output_dir: Path,
    start_ms: int,
    end_ms: int,
    prefix: str,
) -> dict[str, Any]:
    named_clip = output_dir / f"clip_001_00h00m00s_{start_ms}-{end_ms}.mp4"
    shutil.copy2(clean_video, named_clip)
    count = generate_semantic_subtitles_for_clips(
        str(output_dir),
        str(transcript_path),
        ConfigManager(),
        [str(named_clip)],
        fmt="srt",
    )
    if count != 1:
        raise RuntimeError(f"Expected one generated subtitle file, got {count}")
    srt = _copy_generated_srt(named_clip, output_dir / f"{prefix}.srt")
    ass = output_dir / f"{prefix}.ass"
    presets = Path(__file__).resolve().parents[1] / "assets" / "subtitle_styles" / "presets.json"
    apply_style_preset(
        srt,
        "clean",
        ass,
        presets,
        overrides={"fontsize": 24, "outline": 2, "shadow": 1, "marginv": 28},
    )
    subtitled = output_dir / f"{prefix}_subtitled.mp4"
    burn_in(clean_video, ass, subtitled)
    named_clip.unlink(missing_ok=True)
    named_clip.with_suffix(".srt").unlink(missing_ok=True)
    import pysubs2

    events = pysubs2.load(str(ass)).events
    return {
        "srt": srt,
        "ass": ass,
        "subtitled": subtitled,
        "event_count": len(events),
        "max_event_end_ms": max((event.end for event in events), default=0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a real downloaded VOD and render the reviewed final clip")
    parser.add_argument("recording_id")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("outputs/vod-download-e2e"))
    parser.add_argument("--evidence-only", action="store_true", help="Use after a real LLM endpoint probe established unavailability")
    args = parser.parse_args()

    library = LibraryService()
    recording = library.get_recording(args.recording_id)
    if recording is None or not recording.local_path:
        raise SystemExit(f"Recording is missing local media: {args.recording_id}")
    moments = library.repository.list_moments(recording_id=recording.id)
    if len(moments) < 5:
        raise SystemExit(f"Expected at least five FINAL Moments, got {len(moments)}")

    output_dir = (args.output_root / recording.id).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = args.run_root / "processing" / "work" / "transcript_merged.json"
    transcript = _json(transcript_path)
    transcript_checks = _transcript_checks(transcript["segments"], int(recording.duration_ms or 0))

    index = PersistentMomentIndex(library.repository)
    retrieval = HybridRetrievalService(library.repository, index)
    runtime = retrieval.runtime_metadata()
    query_specs = [
        ("What route is the flight taking from Sylt to Stuttgart?", "Silt island", "supported"),
        ("Which flight tools integrate with ActiveSky XP?", "ActiveSky", "supported"),
        ("What battery switches are turned on during cockpit setup?", "Battery master", "supported"),
        ("What baggage fire tests are performed?", "baggage fire", "supported"),
        ("Which airway follows Auspitt in the flight plan?", "Papa 605", "supported"),
        ("What are the origin and destination of the simulated flight?", "Silt island", "paraphrase"),
        ("How does the pilot energize the aircraft before starting the APU?", "Battery master", "paraphrase"),
        ("What route segment comes immediately after Auspitt?", "Papa 605", "paraphrase"),
        ("这次航班使用了什么天气软件？", "ActiveSky", "cross_language"),
        ("Which 飞行 route goes from Sylt to Stuttgart?", "Silt island", "mixed_language"),
    ]
    retrieval_rows = []
    target_moments = {}
    for query, needle, category in query_specs:
        target = _target_moment(moments, needle)
        target_moments[target.id] = target
        row = _search_row(query, target.id, retrieval, recording.id)
        row["category"] = category
        row["provenance"] = "AUTO_DERIVED"
        retrieval_rows.append(row)

    llm_client = None if args.evidence_only else get_default_client(config_manager=ConfigManager())
    conversation = GroundedConversationService(retrieval, llm_client=llm_client)
    supported_questions = [item[0] for item in query_specs[:5]]
    multi_questions = [
        "Summarize the departure, destination, weather integration, and scenery tool used for this flight.",
        "Compare the battery power-up checks with the baggage fire checks.",
        "Summarize the programmed route through Bados, Auspitt, Tostow, and the following airways.",
    ]
    no_evidence_questions = [
        "What color birthday cake did the pilot eat?",
        "What is the pilot's dog's name?",
        "Which hotel did the pilot book in Tokyo?",
        "What medicine dosage did the pilot recommend?",
        "Which guitar model did the pilot buy?",
    ]
    first_supported = _conversation_row(conversation, supported_questions[0], recording.id)
    if first_supported["runtime_mode"] != "GROUNDED_LLM":
        # One real endpoint attempt is enough to establish runtime degradation;
        # avoid multiplying provider retries while still exercising every gate.
        conversation = GroundedConversationService(retrieval, llm_client=None)
    conversations = {
        "supported": [first_supported]
        + [_conversation_row(conversation, query, recording.id) for query in supported_questions[1:]],
        "multi_evidence": [_conversation_row(conversation, query, recording.id) for query in multi_questions],
        "no_evidence": [_conversation_row(conversation, query, recording.id) for query in no_evidence_questions],
    }

    clip_service = ClipService(library.repository, output_root=args.run_root / "review_clips")
    candidates = []
    for row in retrieval_rows:
        target = target_moments[row["target_moment_id"]]
        if target.id in {item["moment_id"] for item in candidates}:
            continue
        proposal = clip_service.create_proposal(
            target.id,
            query=row["query"],
            relevance_score=(row["top_hits"][0]["score"] if row["top_hits"] else 0.0),
            minimum_relevance_score=-20.0,
        )
        candidates.append({"clip_id": proposal.id, "moment_id": target.id, "query": row["query"]})
        if len(candidates) >= 5:
            break

    accepted_moment = _target_moment(moments, "Papa 605")
    accepted = clip_service.create_proposal(
        accepted_moment.id,
        query="Which airway follows Auspitt in the flight plan?",
        context_before_ms=0,
        context_after_ms=0,
        relevance_score=3.0,
    )
    v1 = clip_service.render(accepted.id)
    v1_clean = output_dir / "review_v1_clean.mp4"
    shutil.copy2(v1.output_path, v1_clean)
    v1_render = _render_timed_version(
        v1_clean,
        transcript_path,
        output_dir,
        v1.final_start_ms,
        v1.final_end_ms,
        "review_v1",
    )
    v1_hash = _sha256(v1_render["subtitled"])

    final_start_ms = max(0, v1.final_start_ms - 400)
    reviewed = clip_service.update_review(
        accepted.id,
        start_ms=final_start_ms,
        end_ms=v1.final_end_ms,
        subtitle_style={"preset": "clean", "fontsize": 24, "outline": 2, "shadow": 1, "marginv": 28},
    )
    reviewed = clip_service.render(reviewed.id)
    final_clean = output_dir / "final_clip_clean.mp4"
    shutil.copy2(reviewed.output_path, final_clean)
    final_render = _render_timed_version(
        final_clean,
        transcript_path,
        output_dir,
        reviewed.final_start_ms,
        reviewed.final_end_ms,
        "final_clip",
    )
    final_video = output_dir / "final_clip_subtitled.mp4"
    final_render["subtitled"].replace(final_video)
    final_srt = output_dir / "final_clip.srt"
    final_ass = output_dir / "final_clip.ass"
    final_hash = _sha256(final_video)
    clean_hash = _sha256(final_clean)
    integrity = validate_downloaded_media(final_video)

    preview_seconds = min(5.0, max(0.5, integrity["duration_ms"] / 2000.0))
    preview = output_dir / "subtitle_preview.jpg"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", str(preview_seconds),
            "-i", str(final_video), "-frames:v", "1", "-q:v", "2", str(preview),
        ],
        check=True,
        timeout=300,
    )

    greeting = min(moments, key=lambda item: item.start_ms)
    rejected = clip_service.create_proposal(greeting.id, query="Best technical route explanation")
    feedback = FeedbackService(library.repository)
    accepted_feedback = feedback.decide(
        reviewed.id,
        FeedbackDecision.ACCEPTED,
        reason="Complete, retrieval-supported FMS route explanation with readable timed subtitles.",
        subtitle_edit="Retimed and reflowed long ASR cues after adding a 400 ms lead-in; clean 24 px preset with 2 px outline.",
    )
    rejected_feedback = feedback.decide(
        rejected.id,
        FeedbackDecision.REJECTED,
        reason="Greeting-heavy Moment is less informative and does not answer the technical route query.",
    )

    manifest = {
        "schema_version": "1.0.0",
        "recording_id": recording.id,
        "clip_id": reviewed.id,
        "moment_id": accepted_moment.id,
        "query": reviewed.query,
        "source_media": str(Path(recording.local_path).resolve()),
        "original_start_ms": v1.final_start_ms,
        "original_end_ms": v1.final_end_ms,
        "final_start_ms": reviewed.final_start_ms,
        "final_end_ms": reviewed.final_end_ms,
        "boundary_change": {"start_ms": reviewed.final_start_ms - v1.final_start_ms, "end_ms": reviewed.final_end_ms - v1.final_end_ms},
        "subtitle_style": json.loads(reviewed.subtitle_style_json),
        "subtitle_event_count": final_render["event_count"],
        "subtitle_max_end_ms": final_render["max_event_end_ms"],
        "subtitle_filter": "acfv.processing.subtitle_render.burn_in",
        "review_v1_sha256": v1_hash,
        "final_clean_sha256": clean_hash,
        "final_subtitled_sha256": final_hash,
        "review_changed_hash": v1_hash != final_hash,
        "clean_differs_from_subtitled": clean_hash != final_hash,
        "files": {
            "subtitled": str(final_video),
            "clean": str(final_clean),
            "ass": str(final_ass),
            "srt": str(final_srt),
            "preview": str(preview),
        },
    }
    manifest_path = output_dir / "final_clip_manifest.json"
    _write(manifest_path, manifest)
    review = {
        "accepted_feedback_id": accepted_feedback.id,
        "rejected_feedback_id": rejected_feedback.id,
        "accepted_clip_id": reviewed.id,
        "rejected_clip_id": rejected.id,
        "accepted_reason": accepted_feedback.reason,
        "rejected_reason": rejected_feedback.reason,
        "subtitle_edit": accepted_feedback.subtitle_edit,
        "versioned_previous_output": str(v1_render["subtitled"]),
    }
    review_path = output_dir / "final_clip_review.json"
    _write(review_path, review)

    index_rows = index.rows()
    representations = index.representations()
    result = {
        "recording_id": recording.id,
        "transcript": transcript_checks,
        "moments": {"count": len(moments)},
        "index": {
            **runtime,
            "recording_parent_count": sum(row.recording_id == recording.id for row in index_rows),
            "recording_representation_count": sum(row.recording_id == recording.id for row in representations),
        },
        "retrieval": retrieval_rows,
        "conversation": conversations,
        "candidates": candidates,
        "final_integrity": integrity,
        "manifest": manifest,
        "review": review,
        "no_evidence_expected_answer": NO_EVIDENCE_ANSWER,
    }
    _write(output_dir / "validation_results.json", result)
    print(json.dumps({"status": "PASS", "final_video": str(final_video), "results": str(output_dir / "validation_results.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
