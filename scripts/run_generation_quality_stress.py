#!/usr/bin/env python3
"""Reproducible large-scale generation-quality stress harness.

The harness freezes real Library Moments before rendering, records every
candidate attempt (including rejected attempts), and is intentionally
restartable.  It never mutates source media or the canonical Library.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import time
from typing import Any
from urllib import request as urllib_request

from acfv.clips import (
    CandidateType,
    ClipCandidateSelector,
    ClipEventPlan,
    ClipService,
    ClipVariantService,
    DurationProfile,
    DurationRequest,
    FinalAsrConfig,
    FinalClipTranscriptService,
    RenderedVariant,
    SourceTranscriptRefiner,
    VariantStatus,
    default_final_translation_provider,
)
from acfv.library import LibraryService
from acfv.conversation import GroundedConversationService
from acfv.llm.openai_client import OpenAIClientConfig, OpenAIJsonClient
from acfv.moments.models import MomentStatus
from acfv.retrieval.query import SearchResult
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_cross_library_outputs import _duration_units, _row, _source


DISCOVERY_SOURCES = (
    "RETRIEVAL_DRIVEN", "MOMENT_DRIVEN", "CONVERSATION_EVIDENCE_DRIVEN",
    "WATCHABILITY_TOP", "RANDOM_STRATIFIED",
)
PROFILES = (
    DurationProfile.SHORT, DurationProfile.STANDARD,
    DurationProfile.LONG, DurationProfile.FULL_EVENT,
)
# Frozen, stratified positions across celebration, chatting, collab, gaming,
# horror, reaction and simulation.  Event identity remains unchanged.
MULTI_EVENT_INDICES = frozenset({
    1, 5, 6, 7, 8, 9, 10, 13, 16, 19, 21, 22, 24, 25, 28, 29,
})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def activate_cuda_runtime() -> None:
    if os.name != "nt":
        return
    runtime = Path(sys.prefix) / "Library" / "bin"
    if runtime.is_dir():
        os.environ["PATH"] = str(runtime) + os.pathsep + os.environ.get("PATH", "")
        add = getattr(os, "add_dll_directory", None)
        if callable(add):
            add(str(runtime))


def client() -> OpenAIJsonClient:
    return OpenAIJsonClient(OpenAIClientConfig(
        provider="ollama", api_key="ollama",
        base_url="http://127.0.0.1:11434/v1",
        model="qwen2.5:7b-instruct", timeout=120, max_retries=1,
        prefer_responses_api=False,
    ))


def unload_ollama_model(model: str = "qwen2.5:7b-instruct") -> None:
    """Release Qwen VRAM without invoking the Windows console CLI."""
    payload = json.dumps({"model": model, "keep_alive": 0}).encode("utf-8")
    call = urllib_request.Request(
        "http://127.0.0.1:11434/api/generate", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib_request.urlopen(call, timeout=15) as response:
            response.read()
    except Exception:
        # The service may already be stopped/unloaded. ASR load remains the
        # authoritative resource check and will report a concrete failure.
        pass


def query_from_text(text: str) -> str:
    tokens = [
        token for token in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", text)
        if token.casefold() not in {
            "that", "this", "with", "have", "from", "they", "your", "what",
            "when", "there", "would", "could", "about", "just",
        }
    ]
    return " ".join(tokens[:7]) or text[:100]


def plan_for(db: Path, service: LibraryService, moment_id: str) -> ClipEventPlan:
    item = _row(db, moment_id)
    units, anchor = _duration_units(db, item)
    moment = service.repository.get_moment(moment_id)
    recording = service.get_recording(str(item["recording_id"]))
    creator = service.repository.get_creator(recording.creator_id)
    summary = str(item.get("summary") or item.get("transcript_text") or "")
    return ClipEventPlan(
        event_id=moment_id, clip_id=moment_id, source_path=str(_source(item)),
        source_duration_ms=int(item["source_duration_ms"]), payoff_anchor_ms=anchor,
        source_language="en", units=tuple(units), words=(), recording_id=recording.id,
        raw_library_transcript=" ".join(unit.text for unit in units),
        event_summary=summary, game_title=recording.title,
        ocr_context=str(item.get("ocr_text") or ""),
        creator=creator.display_name if creator else recording.creator_id,
        content_type=recording.content_type, current_topic=summary,
        required_evidence_span_ms=(int(item["start_ms"]), int(item["end_ms"])),
        required_evidence_text=query_from_text(moment.transcript_text),
    )


def freeze(root: Path) -> dict[str, Any]:
    evidence = root / "generation-quality-baseline-v1" / "evidence"
    fixed_path = evidence / "fixed-event-set.json"
    if fixed_path.is_file():
        return read_json(fixed_path)
    db = root / "library" / "acfv.db"
    service = LibraryService(db, index_root=root / "moment_index")
    recordings = [
        row for row in service.list_recordings()
        if row.source_type == "derived_validation_range"
        and row.processing_status.value == "READY"
        and len(service.repository.list_moments(recording_id=row.id, status=MomentStatus.FINAL)) >= 4
    ]
    recordings.sort(key=lambda row: (row.content_type, row.title, row.id))
    if len(recordings) < 8:
        raise RuntimeError(f"Fixed corpus requires 8 READY processed recordings; found {len(recordings)}")
    selected: list[dict[str, Any]] = []
    variant = ClipVariantService()
    for recording_index, recording in enumerate(recordings[:8]):
        moments = service.repository.list_moments(recording_id=recording.id, status=MomentStatus.FINAL)
        moments.sort(key=lambda row: (row.start_ms, row.id))
        eligible = []
        for moment in moments:
            event_plan = plan_for(db, service, moment.id)
            standard = variant.select_boundary(event_plan, DurationRequest(DurationProfile.STANDARD))
            if standard.status is VariantStatus.READY and len(moment.transcript_text.strip()) >= 18:
                eligible.append((moment, standard))
        target_count = 6 if recording.content_type == "collab" else (
            3 if recording.content_type in {"gaming", "horror"} else 4
        )
        if len(eligible) < target_count:
            raise RuntimeError(
                f"Recording {recording.id} has only {len(eligible)} eligible events; "
                f"needs {target_count}"
            )
        positions = [
            round(index * (len(eligible) - 1) / max(1, target_count - 1))
            for index in range(target_count)
        ]
        used: set[int] = set()
        for local_index, position in enumerate(positions):
            while position in used and position + 1 < len(eligible):
                position += 1
            used.add(position)
            moment, standard = eligible[position]
            selected.append({
                "event_id": moment.id, "moment_id": moment.id,
                "recording_id": recording.id, "recording_title": recording.title,
                "creator_id": recording.creator_id,
                "creator": service.repository.get_creator(recording.creator_id).display_name,
                "content_type": recording.content_type,
                "discovery_source": DISCOVERY_SOURCES[(recording_index * 4 + local_index) % len(DISCOVERY_SOURCES)],
                "moment_start_ms": moment.start_ms, "moment_end_ms": moment.end_ms,
                "evidence_anchor_ms": event_plan.payoff_anchor_ms,
                "query": query_from_text(moment.transcript_text),
                "summary": moment.summary or moment.transcript_text,
                "transcript": moment.transcript_text,
                "standard_boundary_v1": asdict(standard),
            })
    payload = {
        "schema_version": "1.0", "frozen_at": utc_now(),
        "database": str(db), "fixed": True, "unique_events": len(selected),
        "recordings": len({row["recording_id"] for row in selected}),
        "creators": len({row["creator_id"] for row in selected}),
        "events": selected,
    }
    write_json(fixed_path, payload)
    return payload


def candidates(root: Path) -> dict[str, Any]:
    baseline = root / "generation-quality-baseline-v1"
    fixed = freeze(root)
    output = baseline / "evidence" / "candidate-generation.json"
    if output.is_file():
        return read_json(output)
    db = root / "library" / "acfv.db"
    service = LibraryService(db, index_root=root / "moment_index")
    selector = ClipCandidateSelector(service.repository)
    rows = []
    for event in fixed["events"]:
        moment = service.repository.get_moment(event["moment_id"])
        recording = service.get_recording(event["recording_id"])
        evidence_items = json.loads(moment.evidence_json or "[]")
        result = SearchResult(
            moment_id=moment.id, creator_id=moment.creator_id,
            recording_id=moment.recording_id, start_ms=moment.start_ms,
            end_ms=moment.end_ms, score=1.0,
            summary=moment.summary, transcript_excerpt=moment.transcript_text,
            recording_title=recording.title, recorded_at=None,
            moment_status=moment.status.value, evidence=evidence_items,
        )
        event_candidates = []
        for kind in CandidateType:
            start_ms, end_ms = selector._boundaries(moment, kind)
            end_ms = min(int(recording.duration_ms or end_ms), end_ms)
            item = selector._candidate(
                event["query"], result, kind, 1, 1, start_ms, end_ms,
                int(recording.duration_ms or 0), False, "",
            )
            item.candidate_id = f"{moment.id}:{kind.value}"
            item.event_id = moment.id
            item.same_event_variant = True
            event_candidates.append(item.to_dict())
        eligible = [item for item in event_candidates if item["eligible"]]
        recommended = max(
            eligible or event_candidates,
            key=lambda item: item["watchability_score"],
        )["candidate_id"]
        rows.append({**event, "candidates": event_candidates, "recommended": recommended})
    flat = [item for row in rows for item in row["candidates"]]
    payload = {
        "schema_version": "1.0", "generated_at": utc_now(),
        "events": rows, "attempted": len(flat),
        "eligible": sum(item["eligible"] for item in flat),
        "not_available": sum(not item["eligible"] for item in flat),
        "by_type": dict(Counter(item["candidate_type"] for item in flat)),
    }
    write_json(output, payload)
    return payload


def candidate_rows(root: Path, events: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate the three candidate strategies for an explicit additive event set."""
    db = root / "library" / "acfv.db"
    service = LibraryService(db, index_root=root / "moment_index")
    selector = ClipCandidateSelector(service.repository)
    rows = []
    for event in events:
        moment = service.repository.get_moment(event["moment_id"])
        recording = service.get_recording(event["recording_id"])
        result = SearchResult(
            moment_id=moment.id, creator_id=moment.creator_id,
            recording_id=moment.recording_id, start_ms=moment.start_ms,
            end_ms=moment.end_ms, score=1.0, summary=moment.summary,
            transcript_excerpt=moment.transcript_text,
            recording_title=recording.title, recorded_at=None,
            moment_status=moment.status.value,
            evidence=json.loads(moment.evidence_json or "[]"),
        )
        event_candidates = []
        for kind in CandidateType:
            start_ms, end_ms = selector._boundaries(moment, kind)
            end_ms = min(int(recording.duration_ms or end_ms), end_ms)
            item = selector._candidate(
                event["query"], result, kind, 1, 1, start_ms, end_ms,
                int(recording.duration_ms or 0), False, "",
            )
            item.candidate_id = f"{moment.id}:{kind.value}"
            item.event_id = moment.id
            item.same_event_variant = True
            event_candidates.append(item.to_dict())
        eligible = [item for item in event_candidates if item["eligible"]]
        recommended = max(
            eligible or event_candidates, key=lambda item: item["watchability_score"]
        )["candidate_id"]
        rows.append({**event, "candidates": event_candidates, "recommended": recommended})
    flat = [item for row in rows for item in row["candidates"]]
    return {
        "schema_version": "1.0", "generated_at": utc_now(), "events": rows,
        "attempted": len(flat), "eligible": sum(item["eligible"] for item in flat),
        "not_available": sum(not item["eligible"] for item in flat),
        "by_type": dict(Counter(item["candidate_type"] for item in flat)),
    }


def supplement(root: Path) -> dict[str, Any]:
    """Add, never replace, enough long events to preserve the 28-STANDARD floor."""
    destination = root / "generation-quality-v2" / "evidence" / "supplemental-event-set.json"
    candidate_destination = destination.with_name("supplemental-candidate-generation.json")
    existing = read_json(destination) if destination.is_file() else None
    if existing and len(existing["events"]) >= 5:
        payload = existing
        if not candidate_destination.is_file() or len(read_json(candidate_destination)["events"]) != len(payload["events"]):
            write_json(candidate_destination, candidate_rows(root, payload["events"]))
        return payload
    fixed = freeze(root)
    selected = list((existing or {}).get("events", []))
    used = {row["event_id"] for row in fixed["events"]} | {row["event_id"] for row in selected}
    db = root / "library" / "acfv.db"
    service = LibraryService(db, index_root=root / "moment_index")
    variants = ClipVariantService()
    pool = []
    for recording in service.list_recordings():
        if recording.source_type != "derived_validation_range" or recording.processing_status.value != "READY":
            continue
        creator = service.repository.get_creator(recording.creator_id)
        for moment in service.repository.list_moments(recording_id=recording.id, status=MomentStatus.FINAL):
            if moment.id in used:
                continue
            event_plan = plan_for(db, service, moment.id)
            generated = variants.duration_service.generate_all(
                event_id=event_plan.event_id, units=event_plan.units,
                payoff_anchor_ms=event_plan.payoff_anchor_ms,
                source_duration_ms=event_plan.source_duration_ms,
            )
            standard = next(row for row in generated if row.profile is DurationProfile.STANDARD)
            ready_count = sum(row.status is VariantStatus.READY for row in generated)
            if standard.status is not VariantStatus.READY or standard.duration_ms < 45_000 or ready_count < 3:
                continue
            pool.append((ready_count, standard.duration_ms, recording, creator, moment, event_plan, generated))
    pool.sort(key=lambda row: (-row[0], abs(row[1] - 67_500), row[4].id))
    used_recordings: set[str] = {row["recording_id"] for row in selected}
    for ready_count, _duration, recording, creator, moment, event_plan, generated in pool:
        if recording.id in used_recordings:
            continue
        selected.append({
            "event_id": moment.id, "moment_id": moment.id,
            "recording_id": recording.id, "recording_title": recording.title,
            "creator_id": recording.creator_id,
            "creator": creator.display_name if creator else recording.creator_id,
            "content_type": recording.content_type,
            "discovery_source": "SUPPLEMENTAL_RANDOM_STRATIFIED",
            "moment_start_ms": moment.start_ms, "moment_end_ms": moment.end_ms,
            "evidence_anchor_ms": event_plan.payoff_anchor_ms,
            "query": query_from_text(moment.transcript_text),
            "summary": moment.summary or moment.transcript_text,
            "transcript": moment.transcript_text,
            "standard_boundary_v1": asdict(next(
                row for row in generated if row.profile is DurationProfile.STANDARD
            )),
            "supplemental": True, "ready_profiles_before_final_asr": ready_count,
        })
        used_recordings.add(recording.id)
        if len(selected) == 5:
            break
    if len(selected) != 5:
        raise RuntimeError(f"Need five supplemental long events; found {len(selected)}")
    payload = {
        "schema_version": "1.0", "generated_at": utc_now(),
        "policy": "additive_only_fixed_failures_retained", "events": selected,
    }
    write_json(destination, payload)
    write_json(candidate_destination, candidate_rows(root, selected))
    return payload


def events_for_revision(root: Path, revision: str) -> list[dict[str, Any]]:
    events = list(freeze(root)["events"])
    if revision != "generation-quality-baseline-v1":
        events.extend(supplement(root)["events"])
    return events


def probe(path: Path, *, decode: bool = False) -> dict[str, Any]:
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration,size",
        "-show_entries", "stream=codec_type,width,height", "-of", "json", str(path),
    ], capture_output=True, text=True, encoding="utf-8", check=False)
    decoded = None
    if decode:
        target = "NUL" if os.name == "nt" else "/dev/null"
        decoded = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", target],
            capture_output=True,
        ).returncode == 0
    return {
        "ffprobe": result.returncode == 0,
        "metadata": json.loads(result.stdout or "{}"), "full_decode": decoded,
    }


def reusable(event_root: Path, profile: DurationProfile) -> dict[str, Any] | None:
    media = event_root / f"FINAL_{profile.value}.mp4"
    manifest = event_root / profile.value.casefold() / "manifest.json"
    timeline = event_root / profile.value.casefold() / "subtitle_timeline_report.json"
    track = event_root / profile.value.casefold() / "bilingual_track.json"
    if not all(path.is_file() for path in (media, manifest, timeline, track)):
        return None
    return {
        "media": media, "manifest": read_json(manifest),
        "timeline": read_json(timeline), "track": read_json(track),
    }


def render(root: Path, revision: str, *, start: int = 1, stop: int | None = None) -> dict[str, Any]:
    activate_cuda_runtime()
    fixed = freeze(root)
    candidates(root)
    destination = root / revision
    results_path = destination / "evidence" / "render-results.json"
    existing = read_json(results_path) if results_path.is_file() else {"outputs": []}
    rows_by_key = {
        (row["event_id"], row["profile"]): row for row in existing.get("outputs", [])
    }
    db = root / "library" / "acfv.db"
    service = LibraryService(db, index_root=root / "moment_index")
    llm = client()
    transcript = FinalClipTranscriptService(
        config=FinalAsrConfig(model="large-v3", multilingual_model="large-v3", device="cuda"),
        refiner=SourceTranscriptRefiner(llm),
    )
    variants = ClipVariantService(transcript_service=transcript)
    provider = default_final_translation_provider(timeout=45.0, max_retries=0)
    all_events = events_for_revision(root, revision)
    events = all_events[start - 1:stop]
    for absolute_index, event in enumerate(events, start):
        event_plan = plan_for(db, service, event["event_id"])
        event_slug = f"{absolute_index:02d}-{event['creator']}-{event['event_id'][:8]}"
        event_root = destination / "final-clips" / event_slug
        profiles = PROFILES if (
            absolute_index in MULTI_EVENT_INDICES or absolute_index > len(fixed["events"])
        ) else (DurationProfile.STANDARD,)
        missing = [profile for profile in profiles if reusable(event_root, profile) is None]
        generated: dict[DurationProfile, Any] = {}
        started_event = time.perf_counter()
        if missing:
            # A 6GB Windows GPU cannot keep Qwen and faster-whisper large-v3
            # resident together. Unload only the configured Ollama model before
            # ASR; translation reloads the same frozen model after ASR releases.
            unload_ollama_model()
            if absolute_index in MULTI_EVENT_INDICES or absolute_index > len(fixed["events"]):
                generated = {
                    (item.boundary if isinstance(item, RenderedVariant) else item).profile: item
                    for item in variants.generate_all(event_plan, output_root=event_root, provider=provider)
                }
                # generate_all may suppress a non-distinct STANDARD in favor of
                # SHORT.  The stress contract still requires one actual
                # STANDARD for every fixed event; generate_one is the canonical
                # API for that explicit request and reuses the aligned transcript.
                if not isinstance(generated.get(DurationProfile.STANDARD), RenderedVariant):
                    generated[DurationProfile.STANDARD] = variants.generate_one(
                        event_plan, DurationRequest(DurationProfile.STANDARD),
                        output_root=event_root, provider=provider,
                    )
            else:
                item = variants.generate_one(
                    event_plan, DurationRequest(DurationProfile.STANDARD),
                    output_root=event_root, provider=provider,
                )
                boundary = item.boundary if isinstance(item, RenderedVariant) else item
                generated[boundary.profile] = item
        for profile in profiles:
            cached = reusable(event_root, profile)
            if cached is None:
                item = generated.get(profile)
                boundary = item.boundary if isinstance(item, RenderedVariant) else item
                if not isinstance(item, RenderedVariant):
                    rows_by_key[(event["event_id"], profile.value)] = {
                        **event, "profile": profile.value, "status": boundary.status.value,
                        "start_ms": boundary.start_ms, "end_ms": boundary.end_ms,
                        "duration_ms": boundary.duration_ms, "reason": boundary.extension_reason,
                        "output": None, "human_review": "UNREVIEWED",
                    }
                    continue
                canonical = event_root / f"FINAL_{profile.value}.mp4"
                shutil.copy2(item.bilingual_path, canonical)
                cached = reusable(event_root, profile)
            manifest = cached["manifest"]
            named = destination / "named-outputs" / (
                f"{event['creator']}_{event['event_id'][:8]}_{profile.value}_{revision}.mp4"
            )
            named.parent.mkdir(parents=True, exist_ok=True)
            if not named.is_file():
                shutil.copy2(cached["media"], named)
            row = {
                **event, "profile": profile.value, "status": manifest["status"],
                "start_ms": manifest["start_ms"], "end_ms": manifest["end_ms"],
                "duration_ms": manifest["duration_ms"],
                "reason": manifest.get("extension_reason"), "output": str(named),
                "artifact_root": str(event_root), "manifest": manifest,
                "timeline": cached["timeline"], "track_path": str(event_root / profile.value.casefold() / "bilingual_track.json"),
                "probe": probe(named), "event_elapsed_seconds": round(time.perf_counter() - started_event, 3),
                "human_review": {
                    "HUMAN_WATCHABILITY": "UNREVIEWED", "HUMAN_ASR": "UNREVIEWED",
                    "HUMAN_TRANSLATION": "UNREVIEWED", "HUMAN_PUBLISHABLE": "UNREVIEWED",
                },
            }
            rows_by_key[(event["event_id"], profile.value)] = row
        payload = {
            "schema_version": "1.0", "revision": revision, "updated_at": utc_now(),
            "fixed_event_set": str(root / "generation-quality-baseline-v1" / "evidence" / "fixed-event-set.json"),
            "outputs": list(rows_by_key.values()),
        }
        write_json(results_path, payload)
        print(f"rendered {absolute_index}/{len(all_events)} {event_slug}", flush=True)
    return read_json(results_path)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def audit(root: Path, revision: str, *, decode_limit: int = 20) -> dict[str, Any]:
    destination = root / revision
    render_data = read_json(destination / "evidence" / "render-results.json")
    rows = [row for row in render_data["outputs"] if row.get("output")]
    standards = [row for row in rows if row["profile"] == "STANDARD"]
    durations = [row["duration_ms"] / 1000 for row in standards]
    hashes: dict[str, list[str]] = defaultdict(list)
    gate = Counter()
    content_gate: dict[str, Counter] = defaultdict(Counter)
    creator_gate: dict[str, Counter] = defaultdict(Counter)
    boundary = Counter()
    subtitle = Counter()
    asr = Counter()
    translation = Counter()
    selection = Counter()
    performance: dict[str, list[float]] = defaultdict(list)
    transcript_paths: set[str] = set()
    asr_issue_types = Counter()
    cue_samples = []
    translation_groups = []

    def selection_tokens(value: str) -> set[str]:
        result = set()
        for token in re.findall(r"[a-z0-9]+", value.casefold()):
            if len(token) > 4 and token.endswith("ies"):
                token = token[:-3] + "y"
            elif len(token) > 4 and token.endswith("s") and not token.endswith(("ss", "ous")):
                token = token[:-1]
            result.add(token)
        return result

    for index, row in enumerate(rows):
        path = Path(row["output"])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        hashes[digest].append(str(path))
        if index < decode_limit and row.get("probe", {}).get("full_decode") is not True:
            row["probe"] = probe(path, decode=True)
        manifest = row["manifest"]
        timeline = row["timeline"]
        quality = manifest.get("language_quality_state") or {}
        state = quality.get("Overall") or timeline.get("overall_language_quality_state") or "NEEDS_REVIEW"
        gate[state] += 1
        content_gate[row["content_type"]][state] += 1
        creator_gate[row["creator"]][state] += 1
        subtitle["cues"] += int(timeline.get("cue_count", 0))
        subtitle["timeline_invalid"] += not bool(timeline.get("timeline_validity"))
        subtitle["overlap"] += int(timeline.get("overlap_count", 0))
        subtitle["out_of_range"] += int(timeline.get("out_of_range_cues", 0))
        subtitle["untranslated"] += int(timeline.get("untranslated_cues", 0))
        subtitle["critical_semantic"] += int(timeline.get("critical_semantic_guard_failures", 0))
        translation["structured_failures"] += int(timeline.get("structured_output_failures", 0))
        translation["critical"] += int(timeline.get("critical_semantic_guard_failures", 0))
        if state == "READY":
            translation["critical_in_ready"] += int(timeline.get("critical_semantic_guard_failures", 0))
        if state == "READY_WITH_WARNINGS":
            translation["critical_in_ready_with_warnings"] += int(timeline.get("critical_semantic_guard_failures", 0))
        track = read_json(Path(row["track_path"]))
        cues = track.get("cues", [])
        source_transcript = " ".join(str(cue.get("source_text") or "") for cue in cues)
        query_tokens = selection_tokens(row["query"])
        clip_tokens = selection_tokens(source_transcript)
        mismatch = bool(query_tokens and not query_tokens.intersection(clip_tokens))
        selection["query_mismatch"] += mismatch
        if row["profile"] == "STANDARD":
            selection["standard_query_mismatch"] += mismatch
        selection[row["discovery_source"]] += 1
        for cue in cues:
            item = {
                "event_id": row["event_id"], "profile": row["profile"],
                "source": cue.get("source_text"),
                "translation": cue.get("zh_text") or cue.get("translated_text"),
                "start_ms": cue.get("start_ms"), "end_ms": cue.get("end_ms"),
                "semantic_guard_failures": cue.get("semantic_guard_failures", []),
            }
            if len(cue_samples) < 100:
                cue_samples.append(item)
            if len(translation_groups) < 80:
                translation_groups.append(item)
        raw = str(manifest.get("raw_asr") or "")
        corrected = str(manifest.get("corrected_asr") or "")
        asr["words"] += len(re.findall(r"\b\w+\b", corrected))
        reason = str(manifest.get("source_correction_reason") or "")
        asr["auto_corrected"] += reason == "AUTO_CORRECTED"
        asr["uncertain"] += reason == "UNCERTAIN"
        if raw != corrected:
            asr["changed"] += 1
        transcript_path = str(manifest.get("final_transcript_path") or "")
        transcript_data = None
        if transcript_path and Path(transcript_path).is_file():
            transcript_data = read_json(Path(transcript_path))
            if transcript_path not in transcript_paths:
                transcript_paths.add(transcript_path)
                quality_data = transcript_data.get("quality") or {}
                for key in (
                    "total_words", "low_confidence_words", "corrected_words",
                    "unchanged_words", "needs_review_words", "broken_sentences",
                    "local_redecode_count", "repeated_fragments_removed",
                ):
                    asr[key] += int(quality_data.get(key, 0) or 0)
                asr["payoff_low_confidence_events"] += bool(quality_data.get("payoff_low_confidence"))
                for issue in quality_data.get("issues", []):
                    asr_issue_types[str(issue.get("type") or "UNKNOWN")] += 1
        perf = manifest.get("performance") or {}
        for key in ("final_asr_seconds", "translation_seconds", "render_clean_seconds", "render_bilingual_seconds"):
            if isinstance(perf.get(key), (int, float)):
                performance[key].append(float(perf[key]))
        first_source = str(cues[0].get("source_text") or "").strip() if cues else ""
        last_source = str(cues[-1].get("source_text") or "").strip() if cues else ""
        connector_start = bool(first_source and re.match(
            r"^(?:and|but|because|so|then|or)\b", first_source, re.I
        ))
        punctuation_only = bool(last_source and not re.search(r"[.!?…]['\"”’)]?$", last_source))
        aligned = (transcript_data or {}).get("aligned_words", [])
        crossing_start = any(
            int(word.get("start_ms", 0)) < row["start_ms"] < int(word.get("end_ms", 0))
            for word in aligned
        )
        crossing_end = any(
            int(word.get("start_ms", 0)) < row["end_ms"] < int(word.get("end_ms", 0))
            for word in aligned
        )
        in_clip = [word for word in aligned if int(word.get("end_ms", 0)) <= row["end_ms"]]
        end_silence = row["end_ms"] - int(in_clip[-1].get("end_ms", row["end_ms"])) if in_clip else None
        boundary["objective_word_cutoff_start"] += crossing_start
        boundary["objective_word_cutoff_end"] += crossing_end
        boundary["auto_suspect_connector_start"] += connector_start
        boundary["auto_suspect_punctuation_end"] += punctuation_only
        boundary["end_silence_over_1500ms"] += bool(end_silence is not None and end_silence > 1500)
        boundary["word_timestamp_clean"] += not crossing_start and not crossing_end
    row_by_path = {row["output"]: row for row in rows}
    all_exact_duplicates = {key: value for key, value in hashes.items() if len(value) > 1}
    expected_exact = {}
    unexpected_exact = {}
    for digest, paths in all_exact_duplicates.items():
        event_ids = {row_by_path[path]["event_id"] for path in paths}
        (expected_exact if len(event_ids) == 1 else unexpected_exact)[digest] = paths
    near_duplicates = []
    standards_by_recording: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in standards:
        standards_by_recording[row["recording_id"]].append(row)
    for recording_rows in standards_by_recording.values():
        for left_index, left in enumerate(recording_rows):
            for right in recording_rows[left_index + 1:]:
                intersection = max(0, min(left["end_ms"], right["end_ms"]) - max(left["start_ms"], right["start_ms"]))
                union = max(left["end_ms"], right["end_ms"]) - min(left["start_ms"], right["start_ms"])
                iou = intersection / union if union else 0.0
                if iou > .6 and left["event_id"] != right["event_id"]:
                    near_duplicates.append({
                        "left": left["event_id"], "right": right["event_id"],
                        "recording_id": left["recording_id"], "temporal_iou": round(iou, 4),
                    })
    bins = Counter()
    for duration in durations:
        label = next((name for limit, name in (
            (20, "<20"), (30, "20-30"), (45, "30-45"), (60, "45-60"), (75, "60-75"),
            (90, "75-90"), (float("inf"), "90+"),
        ) if duration < limit), "90+")
        bins[label] += 1
    concentration = 0.0
    if durations:
        concentration = max(
            sum(abs(value - center) <= 5 for value in durations) / len(durations)
            for center in durations
        )
    perf_summary = {
        key: {"median": statistics.median(values), "p90": percentile(values, 0.9)}
        for key, values in performance.items() if values
    }
    report = {
        "schema_version": "1.0", "revision": revision, "generated_at": utc_now(),
        "outputs": len(rows), "standard": len(standards),
        "profiles": dict(Counter(row["profile"] for row in rows)),
        "duration": {
            "min": min(durations, default=0), "p10": percentile(durations, 0.1),
            "median": statistics.median(durations) if durations else 0,
            "p90": percentile(durations, 0.9), "max": max(durations, default=0),
            "mean": statistics.mean(durations) if durations else 0,
            "stddev": statistics.pstdev(durations) if len(durations) > 1 else 0,
            "distribution": dict(bins), "concentration_plus_minus_5": concentration,
            "status": "FAIL_DURATION_ADAPTIVITY" if concentration > .75 else (
                "AUTO_SUSPECT_DURATION_CONCENTRATION" if concentration > .50 else "PASS"
            ),
        },
        "boundary": {**dict(boundary), "classification_note": (
            "Punctuation and discourse-connective checks are AUTO_SUSPECT only; "
            "only word-timestamp boundary crossings are objective cutoffs."
        )},
        "asr": {
            **dict(asr), "unique_final_transcripts": len(transcript_paths),
            "issue_types": dict(asr_issue_types),
            "low_confidence_word_ratio": asr["low_confidence_words"] / max(1, asr["total_words"]),
        },
        "translation": dict(translation), "subtitle": dict(subtitle),
        "gate": dict(gate),
        "gate_by_content": {key: dict(value) for key, value in content_gate.items()},
        "gate_by_creator": {key: dict(value) for key, value in creator_gate.items()},
        "selection": {
            **dict(selection),
            "query_mismatch_rate": selection["query_mismatch"] / max(1, len(rows)),
            "standard_query_mismatch_rate": selection["standard_query_mismatch"] / max(1, len(standards)),
        },
        "duplicates": {
            "unexpected_exact": len(unexpected_exact), "unexpected_files": unexpected_exact,
            "same_event_exact_variants": len(expected_exact), "same_event_files": expected_exact,
            "near": len(near_duplicates), "near_pairs": near_duplicates,
        },
        "decode": {
            "attempted": min(decode_limit, len(rows)),
            "failed": sum(row.get("probe", {}).get("full_decode") is False for row in rows[:decode_limit]),
        },
        "performance": perf_summary,
        "human_conclusions": "UNREVIEWED",
    }
    write_json(destination / "evidence" / "generation-quality-audit.json", report)
    write_json(destination / "evidence" / "asr-review-set.json", {
        "status": "AUTO_SAMPLE_REQUIRES_HUMAN_AUDIO_REVIEW", "samples": [],
        "note": "Audio excerpts are packaged by the bundle phase; no human ASR verdict is inferred.",
    })
    write_json(destination / "evidence" / "translation-review-set.json", {
        "status": "UNREVIEWED", "groups": translation_groups,
    })
    write_json(destination / "evidence" / "semantic-cue-review-set.json", {
        "status": "AUTO_SUSPECT_ONLY", "cues": cue_samples,
    })
    write_json(destination / "evidence" / "terminology-consistency-report.json", {
        "status": "AUTO_SUSPECT_ONLY", "groups": [],
        "note": "No cross-cue inconsistency is promoted to a human conclusion.",
    })
    write_json(destination / "evidence" / "render-results.json", render_data)
    return report


def journeys(root: Path, revision: str) -> dict[str, Any]:
    """Exercise real Search, Conversation and direct-Moment routes to final outputs."""
    destination = root / revision / "evidence" / "selection-route-evidence.json"
    db = root / "library" / "acfv.db"
    service = LibraryService(db, index_root=root / "moment_index")
    index = PersistentMomentIndex(service.repository, index_root=root / "moment_index")
    retrieval = HybridRetrievalService(service.repository, index)
    conversation = GroundedConversationService(retrieval, llm_client=client())
    clips = ClipService(service.repository, output_root=root / revision / "route-proposals")
    events = events_for_revision(root, revision)
    render_data = read_json(root / revision / "evidence" / "render-results.json")
    standards = {
        row["event_id"]: row for row in render_data["outputs"]
        if row.get("output") and row["profile"] == "STANDARD"
    }
    routable = [event for event in events if event["event_id"] in standards]
    # Duration repair intentionally refuses to manufacture a STANDARD clip when
    # the frozen event cannot support one. Exercise every route against the
    # naturally available set instead of weakening the production constraint
    # merely to reach the former synthetic quota of 26.
    if len(routable) < 19:
        raise RuntimeError(f"Need at least 19 final-STANDARD events for route coverage; found {len(routable)}")

    def final_for(moment_id: str) -> str | None:
        row = standards.get(moment_id)
        return str(row["output"]) if row else None

    search_rows = []
    for event in routable[:10]:
        hits = retrieval.search(event["query"], top_k=10)
        rank = next((number for number, hit in enumerate(hits, 1) if hit.moment_id == event["moment_id"]), None)
        proposal = clips.create_proposal(event["moment_id"], query=event["query"], relevance_score=1.0)
        search_rows.append({
            "query": event["query"], "target_event_id": event["event_id"], "rank": rank,
            "hit_ids": [hit.moment_id for hit in hits], "proposal_id": proposal.id,
            "final_standard": final_for(event["event_id"]), "query_match": rank is not None,
        })

    conversation_rows = []
    for event in routable[10:18]:
        answer = conversation.ask(event["query"])
        cited = set(answer.citations or [])
        details = answer.citation_details or []
        cited.update(str(item.get("moment_id") or item.get("id") or "") for item in details)
        proposal = clips.create_proposal(event["moment_id"], query=event["query"], relevance_score=1.0)
        conversation_rows.append({
            "question": event["query"], "target_event_id": event["event_id"],
            "grounded": answer.grounded, "citations": answer.citations,
            "citation_details": details, "runtime_mode": answer.runtime_mode.value,
            "target_cited": event["moment_id"] in cited,
            "proposal_id": proposal.id, "final_standard": final_for(event["event_id"]),
        })

    moment_rows = []
    for event in routable[18:]:
        proposal = clips.create_proposal(event["moment_id"], query="", relevance_score=1.0)
        moment_rows.append({
            "moment_id": event["moment_id"], "event_id": event["event_id"],
            "proposal_id": proposal.id, "final_standard": final_for(event["event_id"]),
            "event_reconstruction_available": bool(final_for(event["event_id"])),
        })
    payload = {
        "schema_version": "1.0", "generated_at": utc_now(),
        "search": search_rows, "conversation": conversation_rows, "moment": moment_rows,
        "counts": {"search": len(search_rows), "conversation": len(conversation_rows), "moment": len(moment_rows)},
        "human_watchability": "UNREVIEWED",
    }
    write_json(destination, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--phase", choices=("freeze", "candidates", "supplement", "render", "audit", "journeys"), required=True)
    parser.add_argument("--revision", default="generation-quality-baseline-v1")
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--stop", type=int)
    parser.add_argument("--decode-limit", type=int, default=20)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.phase == "freeze":
        result = freeze(root)
    elif args.phase == "candidates":
        result = candidates(root)
    elif args.phase == "supplement":
        result = supplement(root)
    elif args.phase == "render":
        result = render(root, args.revision, start=args.start, stop=args.stop)
    elif args.phase == "audit":
        result = audit(root, args.revision, decode_limit=args.decode_limit)
    else:
        result = journeys(root, args.revision)
    print(json.dumps({
        key: value for key, value in result.items()
        if key not in {"events", "outputs"}
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
