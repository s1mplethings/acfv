from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time
import zipfile

from acfv.clips import (
    ClipEventPlan, ClipVariantService, DurationProfile, DurationRequest,
    FinalAsrConfig, FinalClipTranscriptService, SourceTranscriptRefiner,
    default_final_translation_provider, duration_distribution,
)
from acfv.llm.openai_client import OpenAIClientConfig, OpenAIJsonClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_cross_library_outputs import SELECTIONS, _duration_units, _row, _source


ROOT = Path(__file__).resolve().parents[1]
VARIANT_EVENTS = {
    "0e04994c-e1f1-4875-bd8b-d618f1892353",
    "0861efd7-8afd-4453-b1e9-80341fb58433",
    "5f5dd861-fccb-4adb-a87b-52a7e2cb4e02",
    "5a9caed4-3682-40fc-8bfe-062320a03a59",
    "e1aca6c6-6817-4ed2-acbf-62219fcb4384",
}
CONTENT_TYPES = {
    "8d310288-b8ff-422b-88ea-e28d99deaa1a": "Reaction",
    "5a9caed4-3682-40fc-8bfe-062320a03a59": "Reaction",
    "877e635c-552d-40d8-bab8-cd8fa4756eff": "Reaction",
    "0c6e3e2a-80a8-453c-bcea-1fc8a50eeb66": "Chatting",
    "5f5dd861-fccb-4adb-a87b-52a7e2cb4e02": "Chatting",
    "3ad97744-96b8-4c21-bb0b-5448114308dd": "Chatting",
    "0e04994c-e1f1-4875-bd8b-d618f1892353": "Collab",
    "0861efd7-8afd-4453-b1e9-80341fb58433": "Collab",
    "7c47cf07-ff34-4eb5-bc45-18b822148c12": "Collab",
    "e74cab24-18d0-4baa-9bee-573000bdf5c4": "Simulation/Other",
    "e1aca6c6-6817-4ed2-acbf-62219fcb4384": "Simulation/Other",
    "63c106bf": "Simulation/Other",
}


def _content_type(event_id: str) -> str:
    if event_id in CONTENT_TYPES:
        return CONTENT_TYPES[event_id]
    for prefix, value in CONTENT_TYPES.items():
        if event_id.startswith(prefix):
            return value
    return "Other"


def _activate_runtime() -> None:
    if os.name == "nt":
        runtime = Path(sys.prefix) / "Library" / "bin"
        if runtime.is_dir():
            os.environ["PATH"] = str(runtime) + os.pathsep + os.environ.get("PATH", "")
            add = getattr(os, "add_dll_directory", None)
            if callable(add):
                add(str(runtime))


def _probe(path: Path) -> dict:
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration,size",
        "-show_entries", "stream=codec_type,width,height", "-of", "json", str(path),
    ], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def _plan(library: str, db: Path, moment_id: str) -> ClipEventPlan:
    item = _row(db, moment_id)
    units, anchor = _duration_units(db, item)
    return ClipEventPlan(
        event_id=moment_id, clip_id=moment_id, source_path=str(_source(item)),
        source_duration_ms=int(item["source_duration_ms"]), payoff_anchor_ms=anchor,
        source_language="en", units=tuple(units), words=(), recording_id=str(item["recording_id"]),
        raw_library_transcript=" ".join(unit.text for unit in units),
        event_summary=str(item.get("summary") or item.get("transcript_text") or ""),
        game_title=str(item.get("recording_title") or ""), ocr_context=str(item.get("ocr_text") or ""),
        creator=library, content_type=_content_type(moment_id),
        current_topic=str(item.get("summary") or item.get("transcript_text") or ""),
    )


def _reuse_existing(event_root: Path, library: str, plan: ClipEventPlan,
                    request: DurationRequest, service: ClipVariantService) -> dict | None:
    profile = request.profile
    canonical = event_root / f"FINAL_{profile.value}.mp4"
    profile_root = event_root / profile.value.lower()
    manifest_path = profile_root / "manifest.json"
    timeline_path = profile_root / "subtitle_timeline_report.json"
    if not (canonical.is_file() and manifest_path.is_file() and timeline_path.is_file()):
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    expected = service.select_boundary(plan, request)
    transcript_path = Path(str(manifest.get("final_transcript_path") or ""))
    transcript = (json.loads(transcript_path.read_text(encoding="utf-8"))
                  if transcript_path.is_file() else {})
    if plan.event_id in VARIANT_EVENTS:
        ready = [item for item in service.duration_service.generate_all(
            event_id=plan.event_id, units=plan.units, payoff_anchor_ms=plan.payoff_anchor_ms,
            source_duration_ms=plan.source_duration_ms,
        ) if item.status.value == "READY"]
        desired_start = min(item.start_ms for item in ready)
        desired_end = max(item.end_ms for item in ready)
    else:
        desired_start, desired_end = expected.start_ms, expected.end_ms
    if (transcript.get("event_start_ms") != desired_start or
            transcript.get("event_end_ms") != desired_end):
        return None
    exact_boundary = (
        expected.start_ms == manifest.get("start_ms") and
        expected.end_ms == manifest.get("end_ms")
    )
    word_aligned_boundary = (
        "aligned_word_completion" in str(manifest.get("extension_reason") or "") and
        abs(expected.start_ms - int(manifest.get("start_ms", 0))) <= 2_000 and
        abs(expected.end_ms - int(manifest.get("end_ms", 0))) <= 2_000
    )
    if expected.status.value != manifest.get("status") or not (exact_boundary or word_aligned_boundary):
        return None
    track_path = profile_root / "bilingual_track.json"
    if track_path.is_file():
        track = json.loads(track_path.read_text(encoding="utf-8"))
        cue_providers = {
            "argos" if str(cue.get("localization_note") or "") == "argos_provider_fallback" else "qwen"
            for cue in track.get("cues", [])
        }
        if cue_providers:
            manifest["translation_provider"] = (
                next(iter(cue_providers)) if len(cue_providers) == 1
                else "mixed:" + "+".join(sorted(cue_providers))
            )
    if "performance" not in manifest:
        correction = dict(transcript.get("correction") or {})
        manifest["source_correction_reason"] = correction.get("reason")
        manifest["source_correction_confidence"] = correction.get("confidence")
        manifest["performance"] = {
            "final_event_transcript_total_seconds": transcript.get("wall_time_seconds"),
            "final_asr_seconds": transcript.get("asr_wall_time_seconds"),
            "final_asr_rtf": transcript.get("rtf"),
            "alignment_seconds": transcript.get("alignment_wall_time_seconds"),
            "source_correction_seconds": transcript.get("correction_wall_time_seconds"),
            "translation_seconds": None,
            "render_clean_seconds": None,
            "render_bilingual_seconds": None,
            "vram_mb": None,
            "legacy_runtime_detail": "Per-stage timings unavailable for artifacts rendered before instrumentation",
        }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "library": library, "event_id": plan.event_id, "recording_id": plan.recording_id,
        "content_type": _content_type(plan.event_id),
        "profile": profile.value, "status": manifest["status"],
        "start_ms": manifest["start_ms"], "end_ms": manifest["end_ms"],
        "duration_ms": manifest["duration_ms"],
        "semantic_start_reason": manifest["extension_reason"],
        "semantic_end_reason": manifest["extension_reason"],
        "artifact_role": "FINAL_VARIANT", "is_preview": False,
        "wall_time_seconds": 0.0, "reused": True, "output": str(canonical),
        "probe": _probe(canonical), "manifest": manifest,
        "cue_count": timeline["cue_count"],
        "untranslated_count": timeline["untranslated_cues"],
        "subtitle_timeline_valid": timeline["timeline_validity"],
        "translation_provider": manifest["translation_provider"],
        "translation_mode": manifest["translation_mode"],
        "translation_context_size": manifest["translation_context_size"],
        "final_asr_model": manifest["final_asr_model"],
        "alignment_backend": manifest["alignment_backend"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "var/final_clip_quality/final-clips-v2")
    parser.add_argument("--asr-model", default="large-v3")
    parser.add_argument("--standard-only", action="store_true",
                        help="Regenerate the fixed 12-event STANDARD language/review set only")
    args = parser.parse_args()
    _activate_runtime()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    client = OpenAIJsonClient(OpenAIClientConfig(
        provider="ollama", api_key="ollama", base_url="http://127.0.0.1:11434/v1",
        model="qwen2.5:7b-instruct", timeout=90, max_retries=1, prefer_responses_api=False,
    ))
    transcript_service = FinalClipTranscriptService(
        config=FinalAsrConfig(model=args.asr_model, multilingual_model=args.asr_model, device="cuda"),
        refiner=SourceTranscriptRefiner(client),
    )
    service = ClipVariantService(transcript_service=transcript_service)
    provider = default_final_translation_provider()
    rows: list[dict] = []
    profile_matrix: list[dict] = []
    standard_durations: list[int] = []
    started_all = time.perf_counter()
    for library, (db, moment_ids) in SELECTIONS.items():
        for index, moment_id in enumerate(moment_ids, 1):
            plan = _plan(library, db, moment_id)
            event_root = output / library / f"{index:02d}-{moment_id[:8]}"
            all_boundaries = service.duration_service.generate_all(
                event_id=plan.event_id, units=plan.units, payoff_anchor_ms=plan.payoff_anchor_ms,
                source_duration_ms=plan.source_duration_ms,
            )
            profile_matrix.append({
                "library": library, "event_id": moment_id, "recording_id": plan.recording_id,
                "content_type": _content_type(moment_id),
                "profiles": [{
                    "profile": item.profile.value, "status": item.status.value,
                    "start_ms": item.start_ms, "end_ms": item.end_ms,
                    "duration_ms": item.duration_ms, "reason": item.extension_reason,
                } for item in all_boundaries],
            })
            if moment_id in VARIANT_EVENTS and not args.standard_only:
                available = all_boundaries
                requests = [DurationRequest(item.profile) for item in available if item.status.value == "READY"]
                for item in available:
                    if item.status.value != "READY":
                        rows.append({
                            "library": library, "event_id": moment_id, "recording_id": plan.recording_id,
                            "content_type": _content_type(moment_id),
                            "profile": item.profile.value, "status": item.status.value,
                            "start_ms": item.start_ms, "end_ms": item.end_ms,
                            "duration_ms": item.duration_ms, "semantic_start_reason": item.extension_reason,
                            "semantic_end_reason": item.extension_reason, "artifact_role": "FINAL_VARIANT",
                            "is_preview": False,
                        })
            else:
                requests = [DurationRequest(DurationProfile.STANDARD)]
            generated_results = {}
            if moment_id in VARIANT_EVENTS and not args.standard_only and not any(
                (event_root / f"FINAL_{request.profile.value}.mp4").is_file()
                for request in requests
            ):
                generated_results = {
                    (item.boundary if hasattr(item, "boundary") else item).profile: item
                    for item in service.generate_all(plan, output_root=event_root, provider=provider)
                }
            # Clean variant events use generate_all so every available profile
            # slices one aligned transcript covering their semantic union.
            for request in requests:
                reused = _reuse_existing(event_root, library, plan, request, service)
                if reused is not None:
                    rows.append(reused)
                    if request.profile is DurationProfile.STANDARD:
                        standard_durations.append(reused["duration_ms"])
                    print(f"reused {library} {moment_id[:8]} {request.profile.value}", flush=True)
                    continue
                started = time.perf_counter()
                result = generated_results.get(request.profile)
                if result is None:
                    result = service.generate_one(
                        plan, request, output_root=event_root, provider=provider,
                    )
                boundary = result.boundary if hasattr(result, "boundary") else result
                row = {
                    "library": library, "event_id": moment_id, "recording_id": plan.recording_id,
                    "content_type": _content_type(moment_id),
                    "profile": boundary.profile.value, "status": boundary.status.value,
                    "start_ms": boundary.start_ms, "end_ms": boundary.end_ms,
                    "duration_ms": boundary.duration_ms, "semantic_start_reason": boundary.extension_reason,
                    "semantic_end_reason": boundary.extension_reason, "artifact_role": "FINAL_VARIANT",
                    "is_preview": False, "wall_time_seconds": round(time.perf_counter() - started, 3),
                }
                if hasattr(result, "bilingual_path"):
                    canonical = event_root / f"FINAL_{boundary.profile.value}.mp4"
                    shutil.copy2(result.bilingual_path, canonical)
                    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
                    timeline = json.loads(Path(result.timeline_report_path).read_text(encoding="utf-8"))
                    row.update({
                        "output": str(canonical), "probe": _probe(canonical), "manifest": manifest,
                        "cue_count": timeline["cue_count"], "untranslated_count": timeline["untranslated_cues"],
                        "subtitle_timeline_valid": timeline["timeline_validity"],
                        "translation_provider": manifest["translation_provider"],
                        "translation_mode": manifest["translation_mode"],
                        "translation_context_size": manifest["translation_context_size"],
                        "final_asr_model": manifest["final_asr_model"],
                        "alignment_backend": manifest["alignment_backend"],
                    })
                    if boundary.profile is DurationProfile.STANDARD:
                        standard_durations.append(boundary.duration_ms)
                rows.append(row)
                print(f"final {library} {moment_id[:8]} {boundary.profile.value} {boundary.status.value}", flush=True)
    distribution = duration_distribution(standard_durations)
    report = {
        "schema_version": "1.0", "events": len({row["event_id"] for row in rows}),
        "standard_clips": sum(row["profile"] == "STANDARD" and bool(row.get("output")) for row in rows),
        "variant_clips": sum(row["profile"] != "STANDARD" and bool(row.get("output")) for row in rows),
        "total_final_mp4": sum(bool(row.get("output")) for row in rows), "preview_mp4": 0,
        "duration_distribution": distribution, "clips": rows,
        "duration_profile_matrix": profile_matrix,
        "total_wall_time_seconds": round(time.perf_counter() - started_all, 3),
        "human_quality_review": "PENDING",
    }
    (output / "final-clip-quality-output.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    review = ["# Final Clip Human Review", "", "Only FINAL_VARIANT files are listed; preview proxies are excluded.", ""]
    for row in rows:
        if not row.get("output"):
            continue
        review.extend([f"## {row['library']} / {row['event_id'][:8]} / {row['profile']}", "",
                       f"- File: {row['output']}", f"- Duration: {row['duration_ms'] / 1000:.3f}s",
                       f"- ASR: {row['final_asr_model']}", f"- Alignment: {row['alignment_backend']}",
                       f"- Translation: {row['translation_provider']} / {row['translation_mode']}", "",
                       "ASR: [ ] GOOD [ ] ACCEPTABLE [ ] BAD", "",
                       "TRANSLATION: [ ] GOOD [ ] ACCEPTABLE [ ] BAD", "",
                       "DURATION: [ ] TOO_SHORT [ ] RIGHT [ ] TOO_LONG", "",
                       "OVERALL: [ ] READY [ ] MINOR_EDIT [ ] MAJOR_EDIT [ ] WRONG", "", "---", ""])
    (output / "final-clips-human-review.md").write_text("\n".join(review), encoding="utf-8")
    archive = Path(os.environ.get(
        "ACFV_FINAL_CLIP_ARCHIVE",
        str(Path.home() / ".codex" / "deliverables" / "final-clips-review-bundle.zip"),
    )).resolve()
    archive.parent.mkdir(parents=True, exist_ok=True)
    canonical_names = {f"FINAL_{profile.value}.mp4" for profile in DurationProfile if profile is not DurationProfile.CUSTOM}
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as bundle:
        for path in output.rglob("*"):
            include_metadata = path.name in {
                "final-clip-quality-output.json", "final-clips-human-review.md",
                "manifest.json", "subtitle_timeline_report.json", "bilingual_track.json",
                "clip_zh_en.ass", "clip_zh_en.srt", "variant_comparison.json",
                "variant_review.md", "final_bilingual_duration_review.md",
                "final_language_quality.json", "final_transcript_quality.json",
            }
            if path.is_file() and (path.name in canonical_names or include_metadata):
                bundle.write(path, path.relative_to(output.parent))
    print(json.dumps({"report": str(output / 'final-clip-quality-output.json'),
                      "archive": str(archive), **{key: report[key] for key in
                      ("events", "standard_clips", "variant_clips", "total_final_mp4", "preview_mp4")}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
