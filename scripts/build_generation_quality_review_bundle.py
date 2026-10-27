#!/usr/bin/env python3
"""Build the bounded human-review bundle for generation-quality validation."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
import zipfile
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}\n{result.stderr[-2000:]}")


def review_proxy(source: Path, target: Path) -> None:
    if target.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
        "-vf", "scale=-2:720:force_original_aspect_ratio=decrease",
        "-c:v", "libx264", "-preset", "veryfast", "-b:v", "350k", "-maxrate", "500k",
        "-bufsize", "1000k", "-c:a", "aac", "-b:a", "48k", "-movflags", "+faststart",
        str(target),
    ])


def contact_sheet(source: Path, target: Path, duration_seconds: float) -> None:
    if target.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    interval = max(0.2, duration_seconds / 5)
    run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
        "-vf", f"fps=1/{interval:.3f},scale=320:-2,tile=5x1:padding=4:margin=4",
        "-frames:v", "1", "-q:v", "5", str(target),
    ])


def extract_audio(source: Path, target: Path, start_seconds: float, duration_seconds: float = 8.0) -> None:
    if target.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0, start_seconds):.3f}", "-i", str(source),
        "-t", f"{duration_seconds:.3f}", "-vn", "-c:a", "libmp3lame", "-b:a", "64k",
        str(target),
    ])


def asr_samples(rows: list[dict[str, Any]], stage: Path) -> list[dict[str, Any]]:
    words = []
    for row in rows:
        if row["profile"] != "STANDARD":
            continue
        transcript_path = Path(str(row["manifest"].get("final_transcript_path") or ""))
        if not transcript_path.is_file():
            continue
        transcript = read_json(transcript_path)
        aligned = transcript.get("aligned_words", [])
        for index, word in enumerate(aligned):
            confidence = word.get("confidence")
            if not isinstance(confidence, (int, float)):
                continue
            left = max(0, index - 4)
            right = min(len(aligned), index + 5)
            words.append({
                "event_id": row["event_id"], "creator": row["creator"],
                "output": row["output"], "clip_start_ms": row["start_ms"],
                "word": word.get("text"), "confidence": confidence,
                "word_start_ms": word.get("start_ms"), "word_end_ms": word.get("end_ms"),
                "context": " ".join(str(item.get("text") or "") for item in aligned[left:right]),
                "raw_transcript": transcript.get("raw_final_asr"),
                "final_transcript": transcript.get("corrected_final_transcript"),
            })
    low = sorted(words, key=lambda item: item["confidence"])[:50]
    remaining = [item for item in words if item not in low and item["confidence"] >= .75]
    random.Random(20261012).shuffle(remaining)
    selected = low + remaining[:50]
    for index, item in enumerate(selected, 1):
        relative = (int(item["word_start_ms"]) - int(item["clip_start_ms"])) / 1000 - 3
        target = stage / "asr-samples" / f"{index:03d}-{item['event_id'][:8]}.mp3"
        extract_audio(Path(item["output"]), target, relative)
        item["audio"] = str(target.relative_to(stage)).replace("\\", "/")
        item["sample_class"] = "LOW_CONFIDENCE" if index <= len(low) else "NORMAL_RANDOM"
        item["human_asr"] = "UNREVIEWED"
    write_json(stage / "reports" / "asr-100-span-review-set.json", {
        "status": "UNREVIEWED", "low_confidence": len(low),
        "normal_random": len(selected) - len(low), "samples": selected,
    })
    return selected


def build(root: Path, revision: str, archive: Path) -> dict[str, Any]:
    revision_root = root / revision
    render = read_json(revision_root / "evidence" / "render-results.json")
    audit = read_json(revision_root / "evidence" / "generation-quality-audit.json")
    rows = [row for row in render["outputs"] if row.get("output")]
    stage = root / f"generation-quality-review-bundle-{revision}"
    stage.mkdir(parents=True, exist_ok=True)
    reports = stage / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    for source in (revision_root / "evidence").glob("*.json"):
        shutil.copy2(source, reports / source.name)
    repository_root = Path(__file__).resolve().parents[1]
    for name in ("risk-gate-v2-regression.json", "risk-cluster-analysis.json"):
        source = repository_root / "evidence" / "validation" / name
        if source.is_file():
            shutil.copy2(source, reports / name)
    fixed = root / "generation-quality-baseline-v1" / "evidence" / "fixed-event-set.json"
    candidates = root / "generation-quality-baseline-v1" / "evidence" / "candidate-generation.json"
    shutil.copy2(fixed, reports / fixed.name)
    shutil.copy2(candidates, reports / candidates.name)
    supplemental_candidates = revision_root / "evidence" / "supplemental-candidate-generation.json"
    if supplemental_candidates.is_file():
        shutil.copy2(supplemental_candidates, reports / supplemental_candidates.name)
    baseline_audit_path = root / "generation-quality-baseline-v1" / "evidence" / "generation-quality-audit.json"
    if baseline_audit_path.is_file():
        baseline_audit = read_json(baseline_audit_path)
        comparison = {
            "schema_version": "1.0", "baseline": "generation-quality-baseline-v1",
            "final": revision, "policy": "same_fixed_32_plus_additive_supplemental_events",
            "metrics": {
                "actual_mp4": {"v1": baseline_audit["outputs"], "final": audit["outputs"]},
                "standard": {"v1": baseline_audit["standard"], "final": audit["standard"]},
                "under_20s_standard": {
                    "v1": baseline_audit["duration"]["distribution"].get("<20", 0),
                    "final": audit["duration"]["distribution"].get("<20", 0),
                },
                "objective_start_cutoff": {
                    "v1": baseline_audit["boundary"].get("objective_word_cutoff_start", 0),
                    "final": audit["boundary"].get("objective_word_cutoff_start", 0),
                },
                "objective_end_cutoff": {
                    "v1": baseline_audit["boundary"].get("objective_word_cutoff_end", 0),
                    "final": audit["boundary"].get("objective_word_cutoff_end", 0),
                },
                "standard_query_mismatch_rate": {
                    "v1": baseline_audit["selection"].get("standard_query_mismatch_rate"),
                    "final": audit["selection"].get("standard_query_mismatch_rate"),
                },
                "unexpected_exact_duplicate": {
                    "v1": baseline_audit["duplicates"]["unexpected_exact"],
                    "final": audit["duplicates"]["unexpected_exact"],
                },
                "timeline_invalid": {
                    "v1": baseline_audit["subtitle"]["timeline_invalid"],
                    "final": audit["subtitle"]["timeline_invalid"],
                },
                "full_decode_failed": {
                    "v1": baseline_audit["decode"]["failed"],
                    "final": audit["decode"]["failed"],
                },
            },
        }
        write_json(revision_root / "evidence" / "baseline-vs-final.json", comparison)
        write_json(reports / "baseline-vs-final.json", comparison)
    fixed_payload = read_json(fixed)
    multi_positions = {1, 5, 6, 7, 8, 9, 10, 13, 16, 19, 21, 22, 24, 25, 28, 29}
    multi_event_ids = {
        event["event_id"] for index, event in enumerate(fixed_payload["events"], 1)
        if index in multi_positions
    }
    selected_rows = []
    for row in rows:
        quality = (row.get("manifest") or {}).get("language_quality_state") or {}
        suspect = quality.get("Overall") != "READY"
        multi_group = row["event_id"] in multi_event_ids
        if row["profile"] == "STANDARD" or suspect or multi_group:
            selected_rows.append(row)
    # Deduplicate paths without dropping profile metadata from the index.
    proxy_by_path = {}
    for row in selected_rows:
        source = Path(row["output"])
        filename = source.name
        target = stage / "review-videos" / filename
        if str(source) not in proxy_by_path:
            review_proxy(source, target)
            proxy_by_path[str(source)] = target
        row["review_video"] = str(target.relative_to(stage)).replace("\\", "/")
    for row in rows:
        source = Path(row["output"])
        target = stage / "contact-sheets" / f"{source.stem}.jpg"
        contact_sheet(source, target, row["duration_ms"] / 1000)
        row["contact_sheet"] = str(target.relative_to(stage)).replace("\\", "/")
    samples = asr_samples(standards := [row for row in rows if row["profile"] == "STANDARD"], stage)
    translation_source = revision_root / "evidence" / "translation-review-set.json"
    translation = read_json(translation_source) if translation_source.is_file() else {"groups": []}
    translation["status"] = "UNREVIEWED"
    write_json(reports / "translation-80-group-review-set.json", translation)
    lines = [
        "# ACFV Generation Quality Review Index", "",
        "All human quality labels start as `UNREVIEWED`. Automated flags are suspects, not human conclusions.", "",
    ]
    for row in sorted(rows, key=lambda item: (item["creator"], item["event_id"], item["profile"])):
        quality = (row.get("manifest") or {}).get("language_quality_state") or {}
        track = read_json(Path(row["track_path"]))
        source_text = " ".join(str(cue.get("source_text") or "") for cue in track.get("cues", []))
        translated = " ".join(str(cue.get("translated_text") or "") for cue in track.get("cues", []))
        lines.extend([
            f"## {row['creator']} / {row['event_id'][:8]} / {row['profile']}", "",
            f"- Recording: {row['recording_title']}",
            f"- Content: {row['content_type']}",
            f"- Discovery: {row['discovery_source']}",
            f"- Boundary: {row['start_ms']}–{row['end_ms']} ms",
            f"- Duration: {row['duration_ms'] / 1000:.3f}s",
            f"- Risk: {quality.get('Overall', 'UNKNOWN')}",
            f"- Review video: [{row.get('review_video', 'not packaged')}]({row.get('review_video', '')})",
            f"- Contact sheet: [{row['contact_sheet']}]({row['contact_sheet']})", "",
            f"Source transcript: {source_text}", "",
            f"Translated transcript: {translated}", "",
            "HUMAN_WATCHABILITY: UNREVIEWED", "",
            "HUMAN_ASR: UNREVIEWED", "",
            "HUMAN_TRANSLATION: UNREVIEWED", "",
            "HUMAN_PUBLISHABLE: UNREVIEWED", "", "---", "",
        ])
    (stage / "generation-quality-review-index.md").write_text("\n".join(lines), encoding="utf-8")
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as bundle:
        for path in stage.rglob("*"):
            if path.is_file():
                bundle.write(path, path.relative_to(stage))
    size = archive.stat().st_size
    digest_builder = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest_builder.update(block)
    digest = digest_builder.hexdigest()
    receipt = {
        "archive": str(archive), "size_bytes": size, "sha256": digest,
        "under_500mb": size <= 500 * 1024 * 1024,
        "videos": len(list((stage / "review-videos").glob("*.mp4"))),
        "contact_sheets": len(list((stage / "contact-sheets").glob("*.jpg"))),
        "asr_samples": len(samples), "translation_groups": len(translation.get("groups", [])),
        "review_index": str(stage / "generation-quality-review-index.md"),
        "audit": audit,
    }
    write_json(root / revision / "evidence" / "review-bundle-receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--revision", default="generation-quality-v2")
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.root.resolve(), args.revision, args.archive.resolve()), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
