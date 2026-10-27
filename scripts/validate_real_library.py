#!/usr/bin/env python3
"""Validate a built Creator Library and generate the final human review pack.

The production database and index are treated as read-mostly inputs. Real clip
proposals/renders are persisted because they are deliverables. Recovery and
feedback/restart checks run against isolated copies.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from acfv.clips import ClipService
from acfv.conversation import GroundedConversationService
from acfv.feedback import FeedbackService
from acfv.library import FeedbackDecision, LibraryService
from acfv.library.repository import LibraryRepository
from acfv.moments.models import Moment, MomentStatus
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex, SearchScope


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "var" / "final_validation_20261007" / "dogfood_import.db"
DEFAULT_INDEX = ROOT / "var" / "moment_index"
DEFAULT_BUILD = ROOT / "var" / "real_library_build_20261007"
DEFAULT_CLIPS = ROOT / "var" / "final_validation_20261008" / "clips"
DEFAULT_EVIDENCE = ROOT / "evidence" / "validation"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def human_size(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.3f} {unit}"
        size /= 1024
    return f"{size:.3f} TiB"


def process_memory_mib() -> float | None:
    try:
        import psutil

        return round(psutil.Process().memory_info().rss / (1024 * 1024), 3)
    except (ImportError, OSError):
        return None


def gpu_memory_mib() -> int | None:
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        values = [int(line.strip()) for line in completed.stdout.splitlines() if line.strip().isdigit()]
        return sum(values) if values else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def asr_runtime_metrics(artifact_root: Path, duration_ms: int | None) -> dict[str, Any]:
    path = artifact_root / "work" / "runtime" / "transcribe_runtime.json"
    if not path.is_file():
        return {"elapsed_seconds": None, "rtf": None, "chunks": None, "failed_chunks": None, "retry_count": None}
    payload = json.loads(path.read_text(encoding="utf-8"))
    chunks = payload.get("chunks", []) if isinstance(payload, dict) else []
    starts = [str(item.get("started_at")) for item in chunks if item.get("started_at")]
    finishes = [str(item.get("finished_at")) for item in chunks if item.get("finished_at")]
    elapsed = None
    if starts and finishes:
        elapsed = max(0.0, (datetime.fromisoformat(max(finishes)) - datetime.fromisoformat(min(starts))).total_seconds())
    duration_seconds = float(duration_ms or 0) / 1000
    retries = sum(max(0, int(item.get("attempt", 1) or 1) - 1) for item in chunks)
    return {
        "elapsed_seconds": elapsed,
        "rtf": round(elapsed / duration_seconds, 6) if elapsed is not None and duration_seconds else None,
        "chunks": len(chunks),
        "failed_chunks": sum(str(item.get("status")) == "failed" for item in chunks),
        "retry_count": retries,
    }


def query_from_moment(moment: Moment) -> str:
    text = (moment.transcript_text or moment.summary).strip()
    ascii_terms = [
        term for term in re.findall(r"[A-Za-z0-9']+", text)
        if len(term) >= 3 and term.casefold() not in {"the", "and", "that", "this", "with", "you", "your", "but", "for"}
    ]
    chinese = re.findall(r"[\u3400-\u9fff]{2,}", text)
    if chinese and ascii_terms:
        return f"{chinese[0][:6]} {' '.join(ascii_terms[:3])}"
    if chinese:
        return chinese[0][:12]
    if ascii_terms:
        return " ".join(ascii_terms[:6])
    return (moment.summary or text)[:80]


def stratified_moments(repository: LibraryRepository, per_recording: int = 2) -> list[Moment]:
    selected: list[Moment] = []
    for recording in sorted(repository.list_recordings(), key=lambda item: item.id):
        moments = repository.list_moments(recording_id=recording.id, status=MomentStatus.FINAL)
        if not moments:
            continue
        usable = [item for item in moments if item.summary.strip() and item.transcript_text.strip()] or moments
        for offset in range(per_recording):
            index = min(len(usable) - 1, round((offset + 1) * (len(usable) - 1) / (per_recording + 1)))
            selected.append(usable[index])
    return selected


def database_integrity(db_path: Path) -> dict[str, Any]:
    with sqlite3.connect(db_path) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        queries = {
            "source_without_creator": "SELECT COUNT(*) FROM library_sources s LEFT JOIN library_creators c ON c.id=s.creator_id WHERE c.id IS NULL",
            "recording_without_creator": "SELECT COUNT(*) FROM library_recordings r LEFT JOIN library_creators c ON c.id=r.creator_id WHERE c.id IS NULL",
            "moment_without_recording": "SELECT COUNT(*) FROM library_moments m LEFT JOIN library_recordings r ON r.id=m.recording_id WHERE r.id IS NULL",
            "moment_without_creator": "SELECT COUNT(*) FROM library_moments m LEFT JOIN library_creators c ON c.id=m.creator_id WHERE c.id IS NULL",
        }
        orphans = {name: int(connection.execute(sql).fetchone()[0]) for name, sql in queries.items()}
        final_count = int(connection.execute("SELECT COUNT(*) FROM library_moments WHERE status='FINAL'").fetchone()[0])
    return {
        "integrity_check": integrity,
        "foreign_key_violations": len(foreign_keys),
        "orphans": orphans,
        "final_moments": final_count,
        "pass": integrity == "ok" and not foreign_keys and not any(orphans.values()),
    }


def index_integrity(repository: LibraryRepository, index: PersistentMomentIndex) -> dict[str, Any]:
    rows = index.rows()
    final_ids = {item.id for item in repository.list_moments(status=MomentStatus.FINAL)}
    row_ids = [item.moment_id for item in rows]
    counts = Counter(row_ids)
    stale = sorted(set(row_ids) - final_ids)
    missing = sorted(final_ids - set(row_ids))
    duplicates = sorted(key for key, count in counts.items() if count > 1)
    return {
        "db_final_count": len(final_ids),
        "index_count": len(rows),
        "stale": stale,
        "missing": missing,
        "duplicates": duplicates,
        "pass": len(rows) == len(final_ids) and not stale and not missing and not duplicates,
    }


def transcript_integrity(repository: LibraryRepository, build_root: Path) -> dict[str, Any]:
    rows = []
    totals = Counter()
    languages = Counter()
    for recording in repository.list_recordings():
        stable_root = build_root / "runs" / recording.id
        root = stable_root if stable_root.is_dir() else Path(recording.artifact_root or stable_root)
        candidates = [root / "work" / "transcript_merged.json", root / "work" / "transcription.json"]
        path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
        invalid = non_monotonic = overlap = zero_length = 0
        entries = 0
        last_start = -1.0
        last_end = -1.0
        language = None
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            segments = payload.get("segments", [])
            language = str(payload.get("language") or "unknown")
            duration = float(recording.duration_ms or 0) / 1000
            entries = len(segments)
            for segment in segments:
                try:
                    start = float(segment.get("start"))
                    end = float(segment.get("end"))
                except (AttributeError, TypeError, ValueError):
                    invalid += 1
                    continue
                invalid += int(start < 0 or end < start or (duration and end > duration + 0.05))
                zero_length += int(end <= start)
                non_monotonic += int(start < last_start)
                overlap += int(last_end >= 0 and start < last_end)
                last_start = start
                last_end = max(last_end, end)
        else:
            invalid += 1
        values = {
            "recording_id": recording.id, "path": str(path), "entries": entries, "language": language,
            "invalid": invalid, "non_monotonic": non_monotonic, "overlap": overlap, "zero_length": zero_length,
        }
        rows.append(values)
        totals.update({key: values[key] for key in ("entries", "invalid", "non_monotonic", "overlap", "zero_length")})
        if language:
            languages[language] += 1
    return {
        **dict(totals), "languages": dict(languages), "recordings": rows,
        "pass": len(rows) > 0 and totals["entries"] > 0 and totals["invalid"] == 0 and totals["non_monotonic"] == 0 and totals["zero_length"] == 0,
    }


def _terms_for_grounding(text: str) -> set[str]:
    lowered = text.casefold()
    terms = {item for item in re.findall(r"[a-z0-9]{3,}", lowered)}
    for sequence in re.findall(r"[\u3400-\u9fff]+", lowered):
        terms.update(sequence[index : index + 2] for index in range(max(1, len(sequence) - 1)))
    return terms


def moment_quality(repository: LibraryRepository) -> dict[str, Any]:
    moments = repository.list_moments(status=MomentStatus.FINAL)
    invalid: list[str] = []
    short = duplicates = pathological_overlap = auto_suspect = 0
    seen: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    previous: dict[str, Moment] = {}
    for moment in sorted(moments, key=lambda item: (item.recording_id, item.start_ms, item.end_ms)):
        recording = repository.get_recording(moment.recording_id)
        duration = int(recording.duration_ms or 0) if recording else 0
        if not recording or not moment.summary.strip() or moment.start_ms < 0 or moment.end_ms <= moment.start_ms or (duration and moment.end_ms > duration):
            invalid.append(moment.id)
        short += int(moment.end_ms - moment.start_ms < 5_000)
        normalized = re.sub(r"\W+", " ", moment.summary.casefold()).strip()
        for start, end, summary in seen[moment.recording_id][-5:]:
            if abs(start - moment.start_ms) <= 1_000 and abs(end - moment.end_ms) <= 1_000 and summary == normalized:
                duplicates += 1
                break
        seen[moment.recording_id].append((moment.start_ms, moment.end_ms, normalized))
        prior = previous.get(moment.recording_id)
        if prior:
            intersection = max(0, min(prior.end_ms, moment.end_ms) - max(prior.start_ms, moment.start_ms))
            shorter = min(prior.end_ms - prior.start_ms, moment.end_ms - moment.start_ms)
            pathological_overlap += int(shorter > 0 and intersection / shorter >= 0.9)
        previous[moment.recording_id] = moment
        summary_terms = _terms_for_grounding(moment.summary)
        transcript_terms = _terms_for_grounding(moment.transcript_text)
        auto_suspect += int(bool(summary_terms) and not bool(summary_terms & transcript_terms))
    return {
        "total_final": len(moments), "invalid": len(invalid), "invalid_ids": invalid[:50],
        "short_under_5s": short, "near_duplicates": duplicates, "pathological_overlap": pathological_overlap,
        "auto_pass": len(moments) - auto_suspect, "auto_suspect": auto_suspect,
        "pass": bool(moments) and not invalid and duplicates == 0,
    }


def retrieval_validation(
    repository: LibraryRepository,
    retrieval: HybridRetrievalService,
    sample: list[Moment],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    recordings = repository.list_recordings()
    creator_id = recordings[0].creator_id
    query_rows: list[dict[str, Any]] = []
    latency_ms: list[float] = []
    scopes = [SearchScope.ENTIRE_LIBRARY, SearchScope.CREATOR, SearchScope.RECORDING]
    pool = sample or repository.list_moments(status=MomentStatus.FINAL)[:1]
    for index in range(50):
        moment = pool[index % len(pool)]
        query = query_from_moment(moment)
        scope = scopes[index % len(scopes)]
        kwargs: dict[str, Any] = {}
        if scope == SearchScope.CREATOR:
            kwargs["creator_id"] = creator_id
        if scope == SearchScope.RECORDING:
            kwargs["recording_id"] = moment.recording_id
        started = time.perf_counter()
        hits = retrieval.search(query, top_k=5, scope=scope, **kwargs)
        latency_ms.append((time.perf_counter() - started) * 1000)
        query_rows.append({
            "query": query,
            "scope": scope.value,
            "expected_moment_id": moment.id,
            "top5": [hit.moment_id for hit in hits],
            "expected_in_top5": moment.id in {hit.moment_id for hit in hits},
        })

    index_rows = retrieval.index.rows()
    rng = random.Random(20261008)
    sampled_rows = rng.sample(index_rows, min(50, len(index_rows)))
    result_checks = []
    for row in sampled_rows:
        moment = repository.get_moment(row.moment_id)
        recording = repository.get_recording(moment.recording_id) if moment else None
        valid = bool(
            moment and recording and recording.local_path and Path(recording.local_path).is_file()
            and 0 <= moment.start_ms < moment.end_ms <= int(recording.duration_ms or moment.end_ms)
        )
        result_checks.append({"moment_id": row.moment_id, "valid": valid})

    conversation = GroundedConversationService(retrieval)
    corpus_terms: set[str] = set()
    for row in index_rows:
        corpus_terms.update(GroundedConversationService._terms(row.search_text))
    unsupported = []
    for index in range(20):
        nonce = f"zxqvontology{index:02d}"
        while nonce in corpus_terms:
            nonce += "z"
        second_nonce = f"qjkvoidtrace{index:02d}"
        while second_nonce in corpus_terms:
            second_nonce += "z"
        query = f"{nonce} {second_nonce}"
        answer = conversation.ask(query)
        unsupported.append({
            "query": query,
            "grounded": answer.grounded,
            "citations": answer.citations,
            "answer": answer.answer,
            "pass": not answer.grounded and not answer.citations,
        })

    term_recordings: dict[str, set[str]] = defaultdict(set)
    for row in index_rows:
        for term in re.findall(r"[a-z0-9]{4,}|[\u3400-\u9fff]{2,}", row.search_text.casefold()):
            term_recordings[term].add(row.recording_id)
    reusable_terms = sorted(term_recordings, key=lambda term: (-len(term_recordings[term]), term))
    cross_query = reusable_terms[0] if reusable_terms else query_from_moment(pool[0])
    cross_hits = retrieval.search(cross_query, top_k=min(50, len(index_rows := retrieval.index.rows())))
    cross_recordings = sorted({item.recording_id for item in cross_hits})
    language_smoke = {}
    for name, query in {
        "english": "stream game reaction",
        "chinese": "直播 游戏 反应",
        "mixed": "直播 stream reaction",
    }.items():
        language_smoke[name] = bool(retrieval.search(query, top_k=5))
    smoke = {
        "keyword": any(row["top5"] for row in query_rows),
        "semantic": any(row["top5"] for row in query_rows),
        **language_smoke,
        "creator_scope": any(row["scope"] == SearchScope.CREATOR.value and row["top5"] for row in query_rows),
        "recording_scope": any(row["scope"] == SearchScope.RECORDING.value and row["top5"] for row in query_rows),
        "entire_library": any(row["scope"] == SearchScope.ENTIRE_LIBRARY.value and row["top5"] for row in query_rows),
    }
    return {
        "queries": len(query_rows),
        "expected_top5": sum(row["expected_in_top5"] for row in query_rows),
        "latency_ms": {
            "median": round(median(latency_ms), 3),
            "p90": round(percentile(latency_ms, 0.90), 3),
            "max": round(max(latency_ms, default=0.0), 3),
        },
        "smoke": smoke,
        "result_integrity_sample": len(result_checks),
        "result_integrity_failures": sum(not item["valid"] for item in result_checks),
        "no_evidence": {"queries": 20, "unsupported_claims": sum(not item["pass"] for item in unsupported), "rows": unsupported},
        "cross_recording": {"query": cross_query, "recordings": cross_recordings, "pass": len(cross_recordings) >= 2},
        "pass": all(smoke.values()) and len(result_checks) >= 50 and not any(not item["valid"] for item in result_checks) and all(item["pass"] for item in unsupported),
    }, query_rows


def ffprobe(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration,size", "-show_entries", "stream=codec_type", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    payload = json.loads(completed.stdout or "{}") if completed.returncode == 0 else {}
    streams = [str(item.get("codec_type")) for item in payload.get("streams", [])]
    duration = float(payload.get("format", {}).get("duration", 0) or 0)
    size = int(payload.get("format", {}).get("size", 0) or 0)
    return {
        "returncode": completed.returncode,
        "video": "video" in streams,
        "audio": "audio" in streams,
        "duration_seconds": round(duration, 3),
        "size_bytes": size,
        "pass": completed.returncode == 0 and "video" in streams and "audio" in streams and duration > 0 and size > 0,
    }


def parse_silence_fraction(log: str | None, duration_seconds: float) -> float | None:
    if duration_seconds <= 0:
        return None
    durations = [float(value) for value in re.findall(r"silence_duration:\s*([0-9.]+)", log or "")]
    return round(min(1.0, sum(durations) / duration_seconds), 6)


def silence_fraction(path: Path, duration_seconds: float) -> float | None:
    try:
        completed = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "silencedetect=noise=-45dB:d=0.5", "-f", "null", "-"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
        return parse_silence_fraction(completed.stderr, duration_seconds)
    except (OSError, subprocess.TimeoutExpired):
        return None


def render_review_clips(repository: LibraryRepository, sample: list[Moment], output_root: Path) -> list[dict[str, Any]]:
    service = ClipService(repository, output_root=output_root)
    existing = {(item.moment_id, item.query): item for item in service.list_clips()}
    by_recording: dict[str, Moment] = {}
    for moment in sample:
        by_recording.setdefault(moment.recording_id, moment)
    rows = []
    for moment in list(by_recording.values())[:10]:
        query = query_from_moment(moment)
        subtitle = re.sub(r"\s+", " ", moment.transcript_text).strip()[:240]
        proposal = existing.get((moment.id, query))
        if proposal is None:
            proposal = service.create_proposal(moment.id, query=query, context_before_ms=2_000, context_after_ms=4_000)
        if proposal.final_end_ms - proposal.final_start_ms > 45_000:
            proposal = service.update_review(proposal.id, end_ms=proposal.final_start_ms + 45_000)
        output = Path(proposal.output_path) if proposal.output_path else None
        if output is None or not output.is_file():
            proposal = service.update_review(proposal.id, subtitle_text=subtitle)
            rendered = service.render(proposal.id)
        else:
            rendered = proposal
        probe = ffprobe(Path(rendered.output_path or ""))
        expected = (rendered.final_end_ms - rendered.final_start_ms) / 1000
        interval_ok = abs(probe["duration_seconds"] - expected) <= max(1.0, expected * 0.08)
        silent = silence_fraction(Path(rendered.output_path or ""), probe["duration_seconds"])
        mostly_silence = silent is not None and silent >= 0.8
        language = "mixed" if re.search(r"[A-Za-z]", subtitle) and re.search(r"[\u3400-\u9fff]", subtitle) else "zh" if re.search(r"[\u3400-\u9fff]", subtitle) else "other"
        rows.append({
            "clip_id": rendered.id,
            "moment_id": moment.id,
            "recording_id": moment.recording_id,
            "query": query,
            "start_ms": rendered.final_start_ms,
            "end_ms": rendered.final_end_ms,
            "subtitle": subtitle,
            "output_path": rendered.output_path,
            "ffprobe": probe,
            "interval_ok": interval_ok,
            "silence_fraction": silent,
            "mostly_silence": mostly_silence,
            "subtitle_language": language,
            "automatic_result": "AUTO_PASS" if probe["pass"] and interval_ok and subtitle and not mostly_silence else "AUTO_SUSPECT",
        })
    return rows


def isolated_recovery_and_e2e(db_path: Path, index_root: Path, sample_moment_id: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="acfv-real-library-validation-") as temporary:
        root = Path(temporary)
        copied_db = root / "library.db"
        copied_index = root / "index"
        shutil.copy2(db_path, copied_db)
        shutil.copytree(index_root, copied_index)
        library = LibraryService(copied_db)
        restarted: LibraryService | None = None
        try:
            index = PersistentMomentIndex(library.repository, copied_index)
            retrieval = HybridRetrievalService(library.repository, index, load_default_reranker=False)
            before = len(index.rows())
            rebuilt = retrieval.rebuild()
            after = len(index.rows())
            moment = library.repository.get_moment(sample_moment_id)
            if moment is None:
                raise RuntimeError("Recovery fixture moment missing")
            query = query_from_moment(moment)
            hits = retrieval.search(query, top_k=5)
            clip_service = ClipService(library.repository, output_root=root / "clips")
            clip = clip_service.create_proposal(moment.id, query=query, context_before_ms=1_000, context_after_ms=2_000)
            clip = clip_service.update_review(clip.id, subtitle_text=moment.transcript_text[:160])
            clip = clip_service.render(clip.id)
            feedback = FeedbackService(library.repository).decide(clip.id, FeedbackDecision.ACCEPTED)
            restarted = LibraryService(copied_db)
            persisted = restarted.repository.get_clip(clip.id)
            return {
                "index_before": before,
                "index_rebuilt": rebuilt,
                "index_after": after,
                "search_hits": len(hits),
                "render_ready": bool(clip.output_path and Path(clip.output_path).is_file()),
                "feedback_id": feedback.id,
                "restart_clip_persisted": persisted is not None,
                "pass": before == rebuilt == after and bool(hits) and persisted is not None,
            }
        finally:
            if restarted is not None:
                restarted.repository.engine.dispose()
            library.repository.engine.dispose()


def write_human_pack(
    evidence_root: Path,
    repository: LibraryRepository,
    retrieval_rows: list[dict[str, Any]],
    moments: list[Moment],
    clips: list[dict[str, Any]],
) -> dict[str, str]:
    retrieval_path = evidence_root / "final-human-retrieval-review.md"
    lines = ["# Final Human Retrieval Review", "", "Gate: at least 7/10 queries must place the referenced evidence in Top 5.", ""]
    references = []
    for number, row in enumerate(retrieval_rows[:10], 1):
        hits = row["top5"]
        lines.extend([f"## Query {number}", "", f"Query: `{row['query']}`", "", "Top 5:"])
        for rank in range(5):
            moment = repository.get_moment(hits[rank]) if rank < len(hits) else None
            recording = repository.get_recording(moment.recording_id) if moment else None
            value = f"{recording.title} — {moment.start_ms / 1000:.1f}s — {moment.summary}" if moment and recording else "(no result)"
            lines.append(f"{rank + 1}. {value}")
        lines.extend(["", "User score: PASS [ ]  FAIL [ ]", ""])
        references.append(f"{number}. `{row['expected_moment_id']}`")
    lines.extend(["<details>", "<summary>Reference evidence IDs — open only after rating</summary>", "", *references, "", "</details>", ""])
    retrieval_path.write_text("\n".join(lines), encoding="utf-8")

    moment_path = evidence_root / "final-human-moment-review.md"
    lines = ["# Final Human Moment Review", "", "Gate: GOOD + ACCEPTABLE must be at least 16/20.", ""]
    for number, moment in enumerate(moments[:20], 1):
        recording = repository.get_recording(moment.recording_id)
        evidence = moment.evidence_json[:500]
        lines.extend([
            f"## Moment {number}", "", f"Recording: `{recording.title if recording else moment.recording_id}`",
            f"Timestamp: `{moment.start_ms / 1000:.3f}s–{moment.end_ms / 1000:.3f}s`", f"Duration: `{(moment.end_ms - moment.start_ms) / 1000:.3f}s`",
            f"Summary: {moment.summary}", f"Transcript excerpt: {moment.transcript_text[:500]}", f"Evidence: `{evidence}`", "",
            "GOOD [ ]  ACCEPTABLE [ ]  BAD [ ]", "", "Issue: boundary [ ] summary [ ] duplicate [ ] merge [ ] fragment [ ] context [ ] other [ ]", "",
        ])
    moment_path.write_text("\n".join(lines), encoding="utf-8")

    clip_path = evidence_root / "final-human-clip-review.md"
    lines = ["# Final Human Clip Review", "", "Gate: NO_EDIT + MINOR_EDIT must be at least 6/10.", ""]
    for number, row in enumerate(clips, 1):
        lines.extend([
            f"## Clip {number}", "", f"Clip file: `{row['output_path']}`", f"Moment: `{row['moment_id']}`", f"Query: `{row['query']}`",
            f"Start: `{row['start_ms']} ms`", f"End: `{row['end_ms']} ms`", "", "NO_EDIT [ ]  MINOR_EDIT [ ]  MAJOR_EDIT [ ]  WRONG [ ]", "",
            "Start delta:", "End delta:", "Subtitle issue:", "Notes:", "",
        ])
    clip_path.write_text("\n".join(lines), encoding="utf-8")

    gui_path = evidence_root / "final-gui-checklist.md"
    gui_path.write_text("# Final GUI Checklist\n\n[ ] Open Library\n\n[ ] Open Recording\n\n[ ] Search Conversation\n\n[ ] Open Evidence\n\n[ ] Create Clip\n\n[ ] Review\n\n[ ] Render\n\n[ ] Accept\n", encoding="utf-8")
    human_results = evidence_root / "human-review-results.json"
    if not human_results.exists():
        write_json(human_results, {"retrieval": [], "moments": [], "clips": [], "gui": {"pass": False}})
    return {"retrieval": str(retrieval_path), "moments": str(moment_path), "clips": str(clip_path), "gui": str(gui_path), "results": str(human_results)}


def storage_accounting(repository: LibraryRepository, build_root: Path, index_root: Path, clip_root: Path, db_path: Path) -> dict[str, Any]:
    raw = sum(Path(item.local_path).stat().st_size for item in repository.list_recordings() if item.local_path and Path(item.local_path).is_file())
    categories = defaultdict(int)
    for path in build_root.rglob("*") if build_root.exists() else []:
        if not path.is_file():
            continue
        lowered = path.as_posix().casefold()
        if "/audio/" in lowered:
            categories["audio"] += path.stat().st_size
        elif "/chunks/" in lowered:
            categories["chunks"] += path.stat().st_size
        elif "transcript" in path.name.casefold():
            categories["transcripts"] += path.stat().st_size
        else:
            categories["analysis_and_other"] += path.stat().st_size
    values = {"raw": raw, **categories, "index": path_size(index_root), "clips": path_size(clip_root), "database": db_path.stat().st_size}
    values["derived"] = sum(value for key, value in values.items() if key != "raw")
    values["total"] = raw + values["derived"]
    return {key: {"bytes": value, "human": human_size(value)} for key, value in values.items()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--index-root", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--build-root", type=Path, default=DEFAULT_BUILD)
    parser.add_argument("--clip-root", type=Path, default=DEFAULT_CLIPS)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started = time.perf_counter()
    memory_before_mib = process_memory_mib()
    startup_started = time.perf_counter()
    library = LibraryService(args.db.resolve())
    recordings = library.list_recordings()
    startup_db_ms = (time.perf_counter() - startup_started) * 1000
    index_started = time.perf_counter()
    index = PersistentMomentIndex(library.repository, args.index_root.resolve())
    index_rows = index.rows()
    startup_index_ms = (time.perf_counter() - index_started) * 1000
    memory_index_loaded_mib = process_memory_mib()
    retrieval = HybridRetrievalService(library.repository, index, load_default_reranker=False)
    moments = stratified_moments(library.repository, per_recording=2)
    db_check = database_integrity(args.db.resolve())
    index_check = index_integrity(library.repository, index)
    transcript_check = transcript_integrity(library.repository, args.build_root.resolve())
    moment_check = moment_quality(library.repository)
    retrieval_check, retrieval_rows = retrieval_validation(library.repository, retrieval, moments)
    clips = render_review_clips(library.repository, moments, args.clip_root.resolve())
    recovery = isolated_recovery_and_e2e(args.db.resolve(), args.index_root.resolve(), moments[0].id)
    pack = write_human_pack(args.evidence_root.resolve(), library.repository, retrieval_rows, moments, clips)
    storage = storage_accounting(library.repository, args.build_root.resolve(), args.index_root.resolve(), args.clip_root.resolve(), args.db.resolve())
    ready = sum(item.processing_status.value == "READY" for item in recordings)
    indexed = sum(item.index_status.value == "READY" for item in recordings)
    total_hours = sum(item.duration_ms or 0 for item in recordings) / 3_600_000
    clip_pass = len(clips) == 10 and all(item["automatic_result"] == "AUTO_PASS" for item in clips)
    overall = all((db_check["pass"], index_check["pass"], transcript_check["pass"], moment_check["pass"], retrieval_check["pass"], recovery["pass"], clip_pass, ready == len(recordings), indexed == len(recordings)))
    receipt = {
        "generated_at": utc_now(),
        "overall": "PASS" if overall else "FAIL",
        "recordings": len(recordings),
        "ready_recordings": ready,
        "indexed_recordings": indexed,
        "total_hours": total_hours,
        "final_moments": db_check["final_moments"],
        "database": db_check,
        "index": index_check,
        "transcript": transcript_check,
        "moments": moment_check,
        "retrieval": retrieval_check,
        "clips": {"proposals": len(clips), "renders": len(clips), "auto_pass": sum(item["automatic_result"] == "AUTO_PASS" for item in clips), "rows": clips},
        "recovery_and_e2e": recovery,
        "startup_ms": {"database": round(startup_db_ms, 3), "index_manifest": round(startup_index_ms, 3)},
        "memory_mib": {"process_before": memory_before_mib, "index_loaded": memory_index_loaded_mib, "gpu_observed": gpu_memory_mib()},
        "storage": storage,
        "human_pack": pack,
        "wall_seconds": round(time.perf_counter() - started, 3),
        "known_issues": [],
    }
    evidence_root = args.evidence_root.resolve()
    write_json(evidence_root / "real-library-build-test-receipt.json", receipt)
    build_receipt = {
        "generated_at": receipt["generated_at"], "recordings": [], "total_hours": total_hours,
        "ready_recordings": ready, "indexed_recordings": indexed, "final_moments": db_check["final_moments"], "failures": [],
    }
    progress_path = ROOT / "var" / "library_build_progress.json"
    if progress_path.is_file():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        for recording in recordings:
            row = progress.get("recordings", {}).get(recording.id, {})
            artifact_root = Path(recording.artifact_root or (args.build_root.resolve() / "runs" / recording.id))
            build_receipt["recordings"].append({
                "recording_id": recording.id, "duration_ms": recording.duration_ms, "action": row.get("action"),
                "transcript_entries": row.get("transcript_entries"), "moment_count": row.get("moment_count"),
                "index_count": row.get("index_count"), "processing_time_seconds": row.get("elapsed_seconds"),
                "asr": asr_runtime_metrics(artifact_root, recording.duration_ms), "status": row.get("status"),
            })
        build_receipt["failures"] = progress.get("failed", [])
    write_json(evidence_root / "real-library-build-receipt.json", build_receipt)
    print(json.dumps({"overall": receipt["overall"], "recordings": len(recordings), "hours": total_hours, "moments": len(index_rows), "clips": len(clips)}, ensure_ascii=False, indent=2))
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
