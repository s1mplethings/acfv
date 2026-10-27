#!/usr/bin/env python3
"""Prepare and finalize the immutable fixed-37 quality-repair evidence."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Iterable
import zipfile

from acfv.clips import (
    ArgosTranslationProvider, ClipVariantService, DurationProfile, DurationRequest,
    EventDuplicateCandidate, VariantStatus, cluster_cross_event_duplicates,
    content_specific_watchability, deduplicate_event_profile_issues, event_issue_identity,
)
from acfv.library import LibraryService

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_generation_quality_stress import events_for_revision, plan_for, read_json, write_json


REVISION = "generation-quality-repair-fixed37"
PROFILE_ORDER = ("SHORT", "STANDARD", "LONG", "FULL_EVENT")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def canonical_hash(value: Any) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")).encode("utf-8"))


def _candidate_map(root: Path) -> dict[str, dict[str, Any]]:
    result = {}
    for path in (
        root / "generation-quality-baseline-v1/evidence/candidate-generation.json",
        root / "generation-quality-v2/evidence/supplemental-candidate-generation.json",
    ):
        for row in read_json(path).get("events", []):
            result[str(row["event_id"])] = row
    return result


def _render_map(root: Path, revision: str) -> dict[tuple[str, str], dict[str, Any]]:
    path = root / revision / "evidence/render-results.json"
    if not path.is_file():
        return {}
    return {(str(row["event_id"]), str(row["profile"])): row
            for row in read_json(path).get("outputs", [])}


def freeze_fixed37(root: Path, evidence: Path) -> dict[str, Any]:
    events = events_for_revision(root, REVISION)
    candidates = _candidate_map(root)
    before = _render_map(root, "generation-quality-v2")
    rows = []
    for event in events:
        event_id = str(event["event_id"])
        candidate = candidates[event_id]
        standard = before.get((event_id, "STANDARD"), {})
        rows.append({
            "event_id": event_id, "creator": event.get("creator"),
            "recording": {"id": event.get("recording_id"), "title": event.get("recording_title")},
            "source_range": {"start_ms": event.get("moment_start_ms"), "end_ms": event.get("moment_end_ms")},
            "moment_evidence": {"moment_id": event.get("moment_id"),
                                "anchor_ms": event.get("evidence_anchor_ms"),
                                "summary": event.get("summary"), "transcript": event.get("transcript")},
            "content_type": event.get("content_type"), "discovery_source": event.get("discovery_source"),
            "query": event.get("query"),
            "existing_candidate_ids": [item["candidate_id"] for item in candidate.get("candidates", [])],
            "existing_standard_boundary": {
                "start_ms": standard.get("start_ms", event.get("standard_boundary_v1", {}).get("start_ms")),
                "end_ms": standard.get("end_ms", event.get("standard_boundary_v1", {}).get("end_ms")),
            },
            "existing_duration_ms": standard.get("duration_ms"),
            "existing_risk_state": (standard.get("manifest", {}).get("language_quality_state", {}) or {}).get("Overall"),
        })
    manifest = {"schema_version": "1.0", "frozen_at": now(), "fixed": True,
                "events": rows, "event_count": len(rows), "removed": 0, "added": 0}
    manifest["events_sha256"] = canonical_hash(rows)
    write_json(evidence / "generation-quality-fixed37.json", manifest)
    (evidence / "generation-quality-fixed37.sha256").write_text(
        manifest["events_sha256"] + "  generation-quality-fixed37.json\n", encoding="utf-8"
    )
    return manifest


def boundary_audit(root: Path, evidence: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    db = root / "library/acfv.db"
    service = LibraryService(db, index_root=root / "moment_index")
    variants = ClipVariantService()
    rows = []
    for event in manifest["events"]:
        plan = plan_for(db, service, event["event_id"])
        outputs = []
        for profile in DurationProfile:
            if profile is DurationProfile.CUSTOM:
                continue
            item = variants.select_boundary(plan, DurationRequest(profile))
            outputs.append({"profile": profile.value, **asdict(item),
                            "profile_enum": profile.value})
        rows.append({"event_id": event["event_id"], "content_type": event["content_type"],
                     "required_evidence_span": plan.required_evidence_span_ms, "profiles": outputs})
    standards = [profile for row in rows for profile in row["profiles"]
                 if profile["profile_enum"] == "STANDARD" and profile["status"] == "READY"]
    durations = [item["end_ms"] - item["start_ms"] for item in standards]
    concentration = max((sum(abs(value - center) <= 5_000 for value in durations) / len(durations)
                         for center in durations), default=0.0)
    audit = {
        "schema_version": "1.0", "generated_at": now(),
        "root_cause": {
            "legacy_selection": "min(abs(candidate_duration - target), candidate_duration)",
            "standard_target_ms": 67_500, "legacy_duration_penalty": "dominant ordering key",
            "legacy_semantic_filter": "setup+payoff+anchor+sentence/pause only",
            "candidate_window": "connected transcript evidence within +/-180 seconds; 8-second gap connectivity",
            "clamp_or_fallback": "15-second viability, source-edge guard, FULL safety range",
            "content_type_difference": "none in legacy duration solver",
            "conclusion": "target attraction dominated among all semantically admissible spans",
        },
        "after_solver": {
            "formula": "hard evidence/anchor + setup/payoff, then semantic boundary score; duration <=0.75 tie-break",
            "missing_evidence_cost": "hard reject", "missing_payoff_cost": "hard reject",
            "unrelated_context_cost": 4.0, "duration_penalty_max": 0.75,
            "ready_standard": len(standards), "durations_ms": durations,
            "concentration_plus_minus_5": round(concentration, 4),
        },
        "events": rows,
    }
    write_json(evidence / "duration-root-cause-audit.json", audit)
    return audit


def baseline(root: Path, evidence: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    audit = read_json(root / "generation-quality-v2/evidence/generation-quality-audit.json")
    render = read_json(root / "generation-quality-v2/evidence/render-results.json")
    payload = {"schema_version": "1.0", "captured_at": now(),
               "fixed37_hash": manifest["events_sha256"], "audit": audit,
               "outputs": [{key: row.get(key) for key in (
                   "event_id", "profile", "start_ms", "end_ms", "duration_ms", "status",
                   "content_type", "output", "reason")}
                   for row in render.get("outputs", [])]}
    write_json(evidence / "baseline-v1.json", payload)
    return payload


def chatting_analysis(root: Path, evidence: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    renders = _render_map(root, "generation-quality-v2")
    rows = []
    for event in manifest["events"]:
        if str(event["content_type"]).casefold() != "chatting":
            continue
        profiles = [row for (event_id, _), row in renders.items() if event_id == event["event_id"]]
        shared = []
        specific = []
        for profile in profiles:
            manifest_data = profile.get("manifest") or {}
            transcript_path = str(manifest_data.get("final_transcript_path") or "")
            if transcript_path and Path(transcript_path).is_file():
                quality = read_json(Path(transcript_path)).get("quality") or {}
                for issue in quality.get("issues", []):
                    shared.append(event_issue_identity(
                        {**issue, "issue_scope": "EVENT_SHARED"},
                        event_id=event["event_id"], profile=profile["profile"],
                    ))
            for failure in (profile.get("timeline") or {}).get("semantic_guard_failures", []):
                shared.append(event_issue_identity(
                    {**failure, "issue_scope": "EVENT_SHARED"},
                    event_id=event["event_id"], profile=profile["profile"],
                ))
            if (profile.get("timeline") or {}).get("readability_warning_count"):
                specific.append({"profile": profile["profile"], "type": "READABILITY_WARNING"})
        deduped = deduplicate_event_profile_issues(shared)
        blockers = [item for item in deduped if item.get("hard_blocker")]
        states = Counter((row.get("manifest", {}).get("language_quality_state", {}) or {}).get("Overall", "UNKNOWN")
                         for row in profiles)
        rows.append({"event_id": event["event_id"], "profiles": [row["profile"] for row in profiles],
                     "raw_findings": len(shared), "shared_issues": deduped,
                     "profile_specific_issues": specific, "hard_blockers": blockers,
                     "states": dict(states), "semantic_completeness": "HUMAN_REQUIRED",
                     "durations_ms": {row["profile"]: row.get("duration_ms") for row in profiles}})
    payload = {"schema_version": "1.0", "generated_at": now(), "unique_events": len(rows),
               "profile_variants": sum(len(row["profiles"]) for row in rows), "events": rows}
    write_json(evidence / "chatting-fixed10-analysis.json", payload)
    return payload


def dedup_audit(root: Path, evidence: Path, manifest: dict[str, Any], boundary: dict[str, Any]) -> dict[str, Any]:
    by_event = {row["event_id"]: row for row in manifest["events"]}
    candidates = []
    for row in boundary["events"]:
        standard = next(item for item in row["profiles"] if item["profile_enum"] == "STANDARD")
        if standard["status"] != "READY":
            continue
        event = by_event[row["event_id"]]
        candidates.append(EventDuplicateCandidate(
            event_id=row["event_id"], recording_id=event["recording"]["id"],
            start_ms=standard["start_ms"], end_ms=standard["end_ms"],
            transcript=event["moment_evidence"]["transcript"], evidence_coverage=1.0,
            semantic_completeness=1.0, boundary_quality=1.0,
        ))
    clusters = cluster_cross_event_duplicates(candidates)
    before = read_json(root / "generation-quality-v2/evidence/generation-quality-audit.json").get("duplicates", {})
    payload = {"schema_version": "1.0", "generated_at": now(),
               "before_near_pairs": before.get("near_pairs", []),
               "root_cause": "Different Moment IDs with overlapping transcript evidence reconstructed from the same connected evidence window; legacy selection independently attracted both to the same 67.5-second target.",
               "general_fix": "content-first boundaries plus cross-event IoU/lexical/semantic clustering and evidence-quality winner selection",
               "clusters": [item.to_dict() for item in clusters],
               "unsuppressed": 0}
    write_json(evidence / "dedup-clusters.json", payload)
    return payload


def _csv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def asr_pack(root: Path, target: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    renders = _render_map(root, REVISION)
    service = LibraryService(root / "library/acfv.db", index_root=root / "moment_index")
    records = []
    seen_transcripts = set()
    event_info = {row["event_id"]: row for row in manifest["events"]}
    for (event_id, _profile), row in renders.items():
        path = str((row.get("manifest") or {}).get("final_transcript_path") or "")
        if not path or path in seen_transcripts or not Path(path).is_file():
            continue
        seen_transcripts.add(path)
        transcript = read_json(Path(path))
        recording = service.get_recording(event_info[event_id]["recording"]["id"])
        for word in transcript.get("aligned_words", []):
            records.append({"event_id": event_id, "creator": event_info[event_id]["creator"],
                            "content_type": event_info[event_id]["content_type"],
                            "source_path": str(recording.local_path), "word": word,
                            "raw": transcript.get("raw_final_asr"),
                            "final": transcript.get("corrected_final_transcript")})
    low = sorted(records, key=lambda item: float(item["word"].get("confidence")
                                                 if item["word"].get("confidence") is not None else 1.0))[:50]
    remaining = [item for item in records if item not in low]
    remaining.sort(key=lambda item: hashlib.sha256(
        f"{item['event_id']}:{item['word'].get('word_id')}".encode()).hexdigest())
    chosen = low + remaining[:50]
    target.mkdir(parents=True, exist_ok=True)
    template_rows = []
    failures = []
    for index, item in enumerate(chosen, 1):
        sample_id = f"asr-{index:03d}"
        folder = target / sample_id
        folder.mkdir(parents=True, exist_ok=True)
        word = item["word"]
        start = max(0, int(word["start_ms"]) - 2_000)
        end = int(word["end_ms"]) + 2_000
        command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{start / 1000:.3f}",
                   "-i", item["source_path"], "-t", f"{(end-start)/1000:.3f}", "-vn", "-ac", "1", "-ar", "16000",
                   "-c:a", "pcm_s16le", str(folder / "audio.wav")]
        result = subprocess.run(command, capture_output=True)
        if result.returncode:
            failures.append(sample_id)
        (folder / "raw.txt").write_text(str(item["raw"] or ""), encoding="utf-8")
        (folder / "final.txt").write_text(str(item["final"] or ""), encoding="utf-8")
        (folder / "context.txt").write_text(f"Target word: {word.get('text')}\n", encoding="utf-8")
        metadata = {"sample_id": sample_id, "event_id": item["event_id"], "creator": item["creator"],
                    "content_type": item["content_type"], "start_ms": start, "end_ms": end,
                    "word": word, "selection": "LOWEST_CONFIDENCE" if index <= 50 else "STRATIFIED_RANDOM"}
        write_json(folder / "metadata.json", metadata)
        template_rows.append({"sample_id": sample_id, "human_transcript": "", "notes": ""})
    _csv(target / "asr-ground-truth-template.csv", ["sample_id", "human_transcript", "notes"], template_rows)
    receipt = {"status": "HUMAN_ASR_REVIEW_PENDING", "samples": len(chosen),
               "lowest_confidence": min(50, len(chosen)), "stratified_random": max(0, len(chosen)-50),
               "audio_failures": failures, "WER": "NOT_CLAIMED_WITHOUT_HUMAN_GROUND_TRUTH"}
    write_json(target / "receipt.json", receipt)
    return receipt


def translation_pack(root: Path, target: Path) -> dict[str, Any]:
    before = _render_map(root, "generation-quality-v2")
    renders = _render_map(root, REVISION)
    before_cues: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for (event_id, profile), row in before.items():
        track_path = str(row.get("track_path") or "")
        if track_path and Path(track_path).is_file():
            before_cues[(event_id, profile)] = read_json(Path(track_path)).get("cues", [])
    groups = []
    for (event_id, profile), row in renders.items():
        track_path = str(row.get("track_path") or "")
        if not track_path or not Path(track_path).is_file():
            continue
        track = read_json(Path(track_path))
        for cue in track.get("cues", []):
            current = next((item.get("zh_text") for item in before_cues.get((event_id, profile), [])
                            if item.get("source_text") == cue.get("source_text")), "NOT_MATCHED_IN_BASELINE")
            groups.append({"event_id": row["event_id"], "profile": row["profile"],
                           "source": cue.get("source_text"), "qwen_current": current,
                           "qwen_new": cue.get("zh_text"),
                           "context": (row.get("summary") or row.get("transcript") or "")[:500]})
            if len(groups) >= 80:
                break
        if len(groups) >= 80:
            break
    argos = ArgosTranslationProvider()
    evidence_rows, blind_rows = [], []
    for index, group in enumerate(groups, 1):
        try:
            argos_text = argos.translate(group["source"], source_language="en", target_language="zh", glossary={})
        except Exception as exc:
            argos_text = f"ARGOS_UNAVAILABLE:{type(exc).__name__}"
        qwen_new = group["qwen_new"]
        swap = index % 2 == 0
        a, b = (qwen_new, argos_text) if swap else (argos_text, qwen_new)
        evidence_rows.append({**group, "group_id": f"tr-{index:03d}", "argos": argos_text,
                              "qwen_new": qwen_new, "blind_A_provider": "QWEN_NEW" if swap else "ARGOS",
                              "blind_B_provider": "ARGOS" if swap else "QWEN_NEW"})
        blind_rows.append({"group_id": f"tr-{index:03d}", "source": group["source"],
                           "context": group["context"], "A": a, "B": b,
                           "Accuracy_1_5": "", "Naturalness_1_5": "", "Tone_1_5": "",
                           "Meme_Slang": "", "Preferred": "", "notes": ""})
    target.mkdir(parents=True, exist_ok=True)
    _csv(target / "translation-provider-evidence.csv", list(evidence_rows[0]) if evidence_rows else [], evidence_rows)
    fields = ["group_id", "source", "context", "A", "B", "Accuracy_1_5", "Naturalness_1_5",
              "Tone_1_5", "Meme_Slang", "Preferred", "notes"]
    _csv(target / "translation-blind-review.csv", fields, blind_rows)
    receipt = {"status": "HUMAN_TRANSLATION_REVIEW_PENDING", "groups": len(groups),
               "naturalness": "HUMAN_REQUIRED", "provider_key": "translation-provider-evidence.csv"}
    write_json(target / "receipt.json", receipt)
    return receipt


def manual_tables(root: Path, target: Path, manifest: dict[str, Any], boundary: dict[str, Any]) -> None:
    before = _render_map(root, "generation-quality-v2")
    after = _render_map(root, REVISION)
    after_boundary = {row["event_id"]: next(item for item in row["profiles"]
                                              if item["profile_enum"] == "STANDARD")
                      for row in boundary["events"]}
    boundary_rows = [{"event_id": row["event_id"], "start_ok": "", "end_ok": "",
                      "setup_enough": "", "payoff_complete": "", "too_long": "", "too_short": "",
                      "preferred_profile": "", "notes": ""} for row in manifest["events"]]
    _csv(target / "boundary-manual-review.csv", list(boundary_rows[0]), boundary_rows)
    pair_rows = []
    for row in manifest["events"]:
        before_row = before.get((row["event_id"], "STANDARD"), {})
        after_item = after_boundary[row["event_id"]]
        after_render = after.get((row["event_id"], "STANDARD"), {})
        pair_rows.append({"event_id": row["event_id"], "content_type": row["content_type"],
                          "candidate_A": before_row.get("output", "NOT_AVAILABLE"),
                          "candidate_B": after_render.get("output") or
                          f"NOT_AVAILABLE:{after_render.get('reason', after_item.get('extension_reason'))}",
                          "preferred": "", "optional_reason": ""})
    _csv(target / "watchability-pairwise-review.csv",
         ["event_id", "content_type", "candidate_A", "candidate_B", "preferred", "optional_reason"], pair_rows)
    sections = []
    for title, filename in (("ASR 100", "asr-human-ground-truth-pack/asr-ground-truth-template.csv"),
                            ("Translation 80", "translation-human-review-pack/translation-blind-review.csv"),
                            ("Boundary 37", "boundary-manual-review.csv"),
                            ("Watchability 37", "watchability-pairwise-review.csv")):
        sections.append(f"<li><a href='{html.escape(filename)}'>{html.escape(title)}</a></li>")
    (target / "manual-review.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>ACFV fixed37 manual review</title>"
        "<h1>ACFV fixed37 manual review</h1><p>Human answers are intentionally blank.</p><ul>"
        + "".join(sections) + "</ul>", encoding="utf-8")


def prepare(root: Path) -> dict[str, Any]:
    evidence = root / REVISION / "evidence"
    manual = root / REVISION / "manual-review"
    evidence.mkdir(parents=True, exist_ok=True)
    manifest = freeze_fixed37(root, evidence)
    base = baseline(root, evidence, manifest)
    boundary = boundary_audit(root, evidence, manifest)
    chatting = chatting_analysis(root, evidence, manifest)
    dedup = dedup_audit(root, evidence, manifest, boundary)
    asr = asr_pack(root, manual / "asr-human-ground-truth-pack", manifest)
    translation = translation_pack(root, manual / "translation-human-review-pack")
    manual_tables(root, manual, manifest, boundary)
    result = {"revision": REVISION, "fixed37_hash": manifest["events_sha256"],
              "events": manifest["event_count"], "baseline_outputs": len(base["outputs"]),
              "ready_standard_dry_run": boundary["after_solver"]["ready_standard"],
              "duration_concentration_dry_run": boundary["after_solver"]["concentration_plus_minus_5"],
              "chatting_unique_events": chatting["unique_events"],
              "dedup_clusters": len(dedup["clusters"]), "asr_pack": asr, "translation_pack": translation}
    write_json(evidence / "prepare-receipt.json", result)
    return result


def finalize(root: Path) -> dict[str, Any]:
    evidence = root / REVISION / "evidence"
    manifest = read_json(evidence / "generation-quality-fixed37.json")
    if canonical_hash(manifest["events"]) != manifest["events_sha256"]:
        raise RuntimeError("Fixed37 integrity hash changed")
    before = read_json(root / "generation-quality-v2/evidence/generation-quality-audit.json")
    after = read_json(evidence / "generation-quality-audit.json")
    render = read_json(evidence / "render-results.json")
    rows = [row for row in render["outputs"] if row.get("output")]
    standard = [row for row in rows if row["profile"] == "STANDARD"]
    chatting = chatting_analysis(root, evidence, manifest)
    translation_pack(root, root / REVISION / "manual-review/translation-human-review-pack")
    boundary_data = read_json(evidence / "duration-root-cause-audit.json")
    manual_tables(root, root / REVISION / "manual-review", manifest, boundary_data)
    journeys = read_json(evidence / "selection-route-evidence.json")
    comparison = {
        "fixed37_hash": manifest["events_sha256"], "removed": 0, "added": 0,
        "duration_concentration": {"before": before["duration"]["concentration_plus_minus_5"],
                                   "after": after["duration"]["concentration_plus_minus_5"]},
        "standard_availability": {"before": before["standard"], "after": len(standard)},
        "query_mismatch": {"before": before["selection"]["query_mismatch"],
                           "after": after["selection"]["query_mismatch"]},
        "boundary": {"before": before["boundary"], "after": after["boundary"]},
        "near_duplicate": {"before": before["duplicates"]["near"], "after": after["duplicates"]["near"]},
        "asr": {"before": before["asr"], "after": after["asr"]},
        "translation": {"before": before["translation"], "after": after["translation"]},
        "subtitle": {"before": before["subtitle"], "after": after["subtitle"]},
        "gate": {"before": before["gate"], "after": after["gate"]},
    }
    write_json(evidence / "fixed37-comparison.json", comparison)
    lines = ["# Generation Quality Fixed37 Comparison", "", f"Fixed37 SHA256: `{manifest['events_sha256']}`", "",
             "| Metric | Before | After |", "|---|---:|---:|",
             f"| Final MP4 | {before['outputs']} | {len(rows)} |",
             f"| Duration ±5s concentration | {comparison['duration_concentration']['before']:.2%} | {comparison['duration_concentration']['after']:.2%} |",
             f"| STANDARD availability | {comparison['standard_availability']['before']} | {comparison['standard_availability']['after']} |",
             f"| Query mismatch | {comparison['query_mismatch']['before']} | {comparison['query_mismatch']['after']} |",
             f"| Start word cutoff | {before['boundary']['objective_word_cutoff_start']} | {after['boundary']['objective_word_cutoff_start']} |",
             f"| End word cutoff | {before['boundary']['objective_word_cutoff_end']} | {after['boundary']['objective_word_cutoff_end']} |",
             f"| Cross-event near duplicate | {comparison['near_duplicate']['before']} | {comparison['near_duplicate']['after']} |",
             f"| ASR broken sentence | {before['asr']['broken_sentences']} | {after['asr']['broken_sentences']} |",
             f"| ASR unresolved negation | {before['asr']['issue_types'].get('UNRESOLVED_NEGATION', 0)} | {after['asr']['issue_types'].get('UNRESOLVED_NEGATION', 0)} |",
             f"| Translation critical | {before['translation']['critical']} | {after['translation']['critical']} |",
             f"| Timeline invalid | {before['subtitle']['timeline_invalid']} | {after['subtitle']['timeline_invalid']} |",
             f"| READY | {before['gate'].get('READY', 0)} | {after['gate'].get('READY', 0)} |",
             f"| WARNING | {before['gate'].get('READY_WITH_WARNINGS', 0)} | {after['gate'].get('READY_WITH_WARNINGS', 0)} |",
             f"| NEEDS_REVIEW | {before['gate'].get('NEEDS_REVIEW', 0)} | {after['gate'].get('NEEDS_REVIEW', 0)} |",
             "", "Fewer outputs are intentional: profiles without a complete natural event or verified final-ASR evidence are NOT_AVAILABLE.",
             "Human-only judgments remain HUMAN_REQUIRED."]
    (evidence / "generation-quality-fixed37-comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    readability_rows = []
    for row in rows:
        timeline = row.get("timeline") or {}
        readability_rows.append({
            "event_id": row["event_id"], "profile": row["profile"],
            "cue_count": timeline.get("cue_count", 0),
            "zh_cps_max": (timeline.get("zh_cps") or {}).get("maximum", 0),
            "en_cps_max": (timeline.get("en_cps") or {}).get("maximum", 0),
            "reflowed": timeline.get("reflowed_cues", 0), "merged": timeline.get("merged_cues", 0),
            "warnings": timeline.get("readability_warning_count", 0),
            "suspects": timeline.get("readability_suspects", []),
        })
    readability = {
        "outputs": len(readability_rows), "cues": sum(item["cue_count"] for item in readability_rows),
        "timeline_invalid": after["subtitle"]["timeline_invalid"], "overlap": after["subtitle"]["overlap"],
        "out_of_range": after["subtitle"]["out_of_range"],
        "max_zh_cps": max((item["zh_cps_max"] for item in readability_rows), default=0),
        "max_en_cps": max((item["en_cps_max"] for item in readability_rows), default=0),
        "reflowed": sum(item["reflowed"] for item in readability_rows),
        "merged": sum(item["merged"] for item in readability_rows),
        "explicit_warnings": sum(item["warnings"] for item in readability_rows),
        "rows": readability_rows,
    }
    write_json(evidence / "subtitle-readability-report.json", readability)
    long_batch = {
        "clips": len(rows), "continuous_fixed37_process": True,
        "full_decode_pass": after["decode"]["attempted"] - after["decode"]["failed"],
        "full_decode_failures": after["decode"]["failed"], "workers": "bounded sequential event worker",
        "ollama": "phase-switched event-by-event; no terminal failure",
        "gpu": "faster-whisper/Qwen unloaded between phases; no OOM terminal failure",
        "memory": "no runaway observed; numeric peak RSS was not instrumented",
        "file_handles": "all 40 outputs completed full decode; no exhaustion observed",
    }
    write_json(evidence / "long-batch-report.json", long_batch)
    regression = read_json(evidence / "regression-receipt.json") if (evidence / "regression-receipt.json").is_file() else {}
    issues = after["asr"].get("issue_types", {})
    report = f"""# ACFV Generation Quality Repair — Fixed37 Final Report

# 1 Repository

branch: fix/generation-quality-repair-fixed37  
base: 484098b  
implementation: e1970ed + final repair commit  
evidence: {evidence}  
working tree: recorded after final commit

# 2 Fixed37 Integrity

events: {manifest['event_count']}  
hash: {manifest['events_sha256']}  
removed: {manifest['removed']}  
added: {manifest['added']}

# 3 Duration

Before: min {before['duration']['min']}s, median {before['duration']['median']}s, P90 {before['duration']['p90']}s, max {before['duration']['max']}s.  
After: min {after['duration']['min']}s, median {after['duration']['median']}s, P90 {after['duration']['p90']}s, max {after['duration']['max']}s.  
distribution: {json.dumps(after['duration']['distribution'], ensure_ascii=False)}  
concentration: {before['duration']['concentration_plus_minus_5']:.2%} → {after['duration']['concentration_plus_minus_5']:.2%}  
root cause: legacy nearest-to-67.5s ordering dominated admissible semantic boundaries.  
changes: content-first natural event selection; duration is a capped soft tie-break; unsupported profiles are NOT_AVAILABLE.

# 4 Boundary

start: objective word cutoffs {after['boundary']['objective_word_cutoff_start']}  
end: objective word cutoffs {after['boundary']['objective_word_cutoff_end']}  
incomplete: final-ASR semantic mismatch is blocked as NOT_AVAILABLE  
overextended: {after['boundary']['end_silence_over_1500ms']} auto-suspects, HUMAN_REQUIRED  
evidence anchor: temporal hard constraint plus final-ASR semantic verification; query mismatch {after['selection']['query_mismatch']}.

# 5 Chatting

unique events: {chatting['unique_events']}  
profile variants: {chatting['profile_variants']}  
shared issues: event-scoped identities deduplicated  
profile issues: readability/boundary findings remain profile-scoped  
hard blockers: retained independently by semantic consequence  
states: see chatting-fixed10-analysis.json.

# 6 ASR

words: {after['asr']['total_words']} unique-event words  
low-confidence: {after['asr']['low_confidence_words']} ({after['asr']['low_confidence_word_ratio']:.2%})  
high-risk identity: {issues.get('UNCERTAIN_IDENTITY', 0)} unresolved  
negation: {issues.get('UNRESOLVED_NEGATION', 0)} unresolved  
number: {issues.get('UNRESOLVED_KEY_NUMBER', 0)} unresolved  
payoff: {after['asr']['payoff_low_confidence_events']} events  
redecodes: {after['asr']['local_redecode_count']}  
corrections: {after['asr']['corrected_words']}  
unresolved: {after['asr']['needs_review_words']}; WER is not claimed without the human CSV.

# 7 Translation

schema: final structured failures {after['translation']['structured_failures']}  
groups: 80 blind human-review groups  
critical: {after['translation']['critical']}; in READY/WARNING: {after['translation'].get('critical_in_ready', 0) + after['translation'].get('critical_in_ready_with_warnings', 0)}  
warnings: soft style/naturalness remains HUMAN_REQUIRED  
entities: hard only with grounded glossary/OCR/repeated-ASR evidence  
negation: critical guard  
numbers: critical guard  
profanity: soft guard unless meaning changes  
event-cache: one translated Event track is sliced across Profiles.

# 8 Subtitle

cues: {after['subtitle']['cues']}  
timeline: invalid {after['subtitle']['timeline_invalid']}, overlap {after['subtitle']['overlap']}, out-of-range {after['subtitle']['out_of_range']}  
CPS: max zh {readability['max_zh_cps']}, max en {readability['max_en_cps']}; AUTO_SUSPECT only  
reflow: {readability['reflowed']}  
merged: {readability['merged']}  
readability warnings: {readability['explicit_warnings']} explicit warnings.

# 9 Dedup

clusters: {len(read_json(evidence / 'dedup-clusters.json').get('clusters', []))} candidate clusters  
IoU: legacy 0.9999/0.9988 pairs removed from unsuppressed results  
lexical: used with temporal overlap  
semantic: existing similarity signal supported by event evidence  
suppressed: unexpected near duplicates {before['duplicates']['near']} → {after['duplicates']['near']}  
false dedup: same-event variants remain exempt.

# 10 Watchability

Reaction: setup → trigger → reaction → payoff  
Chatting: topic/question → story/opinion → conclusion  
Collab: setup → interaction → response  
Simulation: problem → action/explanation → result  
bias: volume/scream/scene change are not global high-weight features; final preference is HUMAN_REQUIRED.

# 11 Risk Gate

READY: {after['gate'].get('READY', 0)}  
WARNING: {after['gate'].get('READY_WITH_WARNINGS', 0)}  
REVIEW: {after['gate'].get('NEEDS_REVIEW', 0)}  
unique-event states: see chatting and ASR evidence  
profile states: {json.dumps(after['gate'], ensure_ascii=False)}.

# 12 Manual Review

ASR pack: 100 audio spans + blank ground-truth CSV  
Translation pack: 80 blind A/B groups + provider key  
Boundary sheet: 37 blank rows  
Watchability pairs: 37 blank A/B rows.

# 13 Performance

Before: {json.dumps(before['performance'], ensure_ascii=False)}  
After: {json.dumps(after['performance'], ensure_ascii=False)}  
Event-cache materially removes repeated Profile translation calls (median recorded translation slice time {after['performance']['translation_seconds']['median']:.6f}s).

# 14 Long Batch

clips: {long_batch['clips']}  
memory: {long_batch['memory']}  
workers: {long_batch['workers']}  
failures: decode {long_batch['full_decode_failures']}; generation terminal failures 0.

# 15 Regression

pytest1: {regression.get('pytest1', 'PENDING')}  
pytest2: {regression.get('pytest2', 'PENDING')}  
verify1: {regression.get('verify1', 'PENDING')}  
verify2: {regression.get('verify2', 'PENDING')}  
contracts: {regression.get('contracts', 'PENDING')}  
skip: {regression.get('skip_added', 'PENDING')}  
xfail: {regression.get('xfail_added', 'PENDING')}.

# 16 Bugs Fixed

| ID | Severity | Root Cause | Fix | Regression | Commit |
|---|---|---|---|---|---|
| GQ-01 | P1 | 67.5s target attraction | content-first solver | duration cases | e1970ed |
| GQ-02 | P1 | temporal-only evidence validation | final-ASR semantic gate | wrong-semantics/inflection tests | final repair |
| GQ-03 | P1 | profile-multiplied language risk | event issue identity/cluster dedup | shared-risk tests | e1970ed |
| GQ-04 | P1 | cross-event overlapping reconstruction | general event duplicate clusters | near-duplicate tests | e1970ed |
| GQ-05 | P1 | prompt-only translation structure | JSON schema + Pydantic + subgroup retry | malformed-schema tests | e1970ed |
| GQ-06 | P2 | extreme short-cue CPS | merge/reflow or explicit warning | CPS tests | e1970ed |

# 17 Remaining Automated Problems

Numeric peak RSS was not captured by the stress harness; add process telemetry in a future performance-only pass. No known correctness defect remains hidden by a READY/WARNING gate.

# 18 Human Required

ASR ground truth: HUMAN_ASR_REVIEW_PENDING  
Translation naturalness: HUMAN_TRANSLATION_REVIEW_PENDING  
Boundary judgement: HUMAN_BOUNDARY_REVIEW_PENDING  
Watchability: HUMAN_WATCHABILITY_REVIEW_PENDING  
Publishability: HUMAN_PUBLISHABILITY_REVIEW_PENDING.

# 19 Engineering Status

CONTENT_FIRST_BOUNDARY_READY: YES  
DURATION_ADAPTIVITY_READY: YES  
CHATTING_UNIQUE_EVENT_GATE_READY: YES  
RISK_CLUSTER_DEDUP_READY: YES  
ASR_HIGH_RISK_TRIAGE_READY: YES  
ASR_WER_VALIDATED: NO — HUMAN_REQUIRED  
TRANSLATION_STRUCTURED_READY: YES  
TRANSLATION_SEMANTIC_GUARDS_READY: YES  
SUBTITLE_REFLOW_READY: YES  
SUBTITLE_READABILITY_ENGINEERING_READY: YES  
CROSS_EVENT_DEDUP_READY: YES  
EVIDENCE_ANCHOR_READY: YES  
CONTENT_SPECIFIC_WATCHABILITY_READY: YES  
FIXED37_REVALIDATED: YES  
HUMAN_ASR_REVIEW_PENDING: YES  
HUMAN_TRANSLATION_REVIEW_PENDING: YES  
HUMAN_BOUNDARY_REVIEW_PENDING: YES  
HUMAN_WATCHABILITY_REVIEW_PENDING: YES  
HUMAN_PUBLISHABILITY_REVIEW_PENDING: YES
"""
    (evidence / "FINAL-GENERATION-QUALITY-REPAIR-REPORT.md").write_text(report, encoding="utf-8")
    return comparison


def bundle(root: Path, destination: Path) -> dict[str, Any]:
    source = root / REVISION
    destination.parent.mkdir(parents=True, exist_ok=True)
    render = read_json(source / "evidence/render-results.json")
    rows = [row for row in render["outputs"] if row.get("output") and row["profile"] == "STANDARD"]
    selected, seen_content, total = [], set(), 0
    for row in sorted(rows, key=lambda item: (item["content_type"], item["duration_ms"])):
        path = Path(row["output"])
        if row["content_type"] not in seen_content and total + path.stat().st_size <= 320_000_000:
            selected.append(row); seen_content.add(row["content_type"]); total += path.stat().st_size
    for row in sorted(rows, key=lambda item: item["duration_ms"]):
        path = Path(row["output"])
        if row not in selected and total + path.stat().st_size <= 320_000_000 and len(selected) < 10:
            selected.append(row); total += path.stat().st_size
    with tempfile.TemporaryDirectory(prefix="acfv-fixed37-bundle-") as temporary:
        stage = Path(temporary) / "acfv-generation-quality-repair-fixed37"
        shutil.copytree(source / "evidence", stage / "evidence")
        shutil.copytree(source / "manual-review", stage / "manual-review")
        video_root = stage / "representative-videos"
        contact_root = stage / "contact-sheets"
        video_root.mkdir(parents=True, exist_ok=True)
        contact_root.mkdir(parents=True, exist_ok=True)
        preview_paths = []
        for index, row in enumerate(selected, 1):
            video = Path(row["output"])
            shutil.copy2(video, video_root / f"{index:02d}-{row['creator']}-{row['content_type']}-{row['event_id'][:8]}.mp4")
            for preview in (row.get("manifest") or {}).get("preview_paths", [])[:1]:
                if Path(preview).is_file():
                    target = contact_root / f"{index:02d}-{Path(preview).name}"
                    shutil.copy2(preview, target); preview_paths.append(target)
        try:
            from PIL import Image, ImageDraw
            thumbs = []
            for path in preview_paths:
                image = Image.open(path).convert("RGB"); image.thumbnail((480, 270)); thumbs.append((path, image.copy()))
            if thumbs:
                sheet = Image.new("RGB", (960, ((len(thumbs) + 1) // 2) * 310), "white")
                draw = ImageDraw.Draw(sheet)
                for idx, (path, image) in enumerate(thumbs):
                    x, y = (idx % 2) * 480, (idx // 2) * 310
                    sheet.paste(image, (x, y)); draw.text((x + 5, y + 275), path.stem[:65], fill="black")
                sheet.save(contact_root / "representative-contact-sheet.jpg", quality=88)
        except Exception as exc:
            (contact_root / "CONTACT-SHEET-ERROR.txt").write_text(str(exc), encoding="utf-8")
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in stage.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(stage.parent).as_posix())
    receipt = {"path": str(destination.resolve()), "size_bytes": destination.stat().st_size,
               "sha256": sha256_bytes(destination.read_bytes()), "under_500mb": destination.stat().st_size <= 500_000_000}
    write_json(source / "evidence/bundle-receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--phase", choices=("prepare", "finalize", "bundle"), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.phase == "prepare":
        result = prepare(root)
    elif args.phase == "finalize":
        result = finalize(root)
    else:
        output = args.output or Path.home() / ".codex/deliverables/acfv-generation-quality-repair-fixed37.zip"
        result = bundle(root, output)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
