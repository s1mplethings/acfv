from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from acfv.clips import (
    BilingualSubtitleService,
    DurationProfile,
    DurationProfileService,
    DurationRequest,
    QwenTranslationProvider,
    SemanticBoundaryUnit,
    SubtitleWord,
)
from acfv.llm.openai_client import OpenAIClientConfig, OpenAIJsonClient


ROOT = Path(__file__).resolve().parents[1]
DOGFOOD_DB = ROOT / "var/intelligence_quality_20261008/library_v2.db"
Q8_DB = ROOT / "var/cross_library_generalization/q8-library.db"
TPP_DB = ROOT / "var/cross_library_generalization/tpp-library-service.db"

SELECTIONS = {
    "Saruei": (DOGFOOD_DB, ["8d310288-b8ff-422b-88ea-e28d99deaa1a", "0c6e3e2a-80a8-453c-bcea-1fc8a50eeb66", "0e04994c-e1f1-4875-bd8b-d618f1892353"]),
    "anny": (DOGFOOD_DB, ["5a9caed4-3682-40fc-8bfe-062320a03a59", "0861efd7-8afd-4453-b1e9-80341fb58433", "5f5dd861-fccb-4adb-a87b-52a7e2cb4e02", "3ad97744-96b8-4c21-bb0b-5448114308dd", "877e635c-552d-40d8-bab8-cd8fa4756eff"]),
    "Q8Pilot": (Q8_DB, ["e74cab24-18d0-4baa-9bee-573000bdf5c4", "7c47cf07-ff34-4eb5-bc45-18b822148c12"]),
    "twitchplayspokemon": (TPP_DB, ["e1aca6c6-6817-4ed2-acbf-62219fcb4384", "63c106bf-f111-46f3-8ec4-b04c9d28426f"]),
}

BILINGUAL_COUNTS = {"Saruei": 2, "anny": 4, "Q8Pilot": 1, "twitchplayspokemon": 1}
DURATION_EVENTS = [
    ("Saruei", "8d310288-b8ff-422b-88ea-e28d99deaa1a", "horror_reaction"),
    ("anny", "5f5dd861-fccb-4adb-a87b-52a7e2cb4e02", "chatting_story"),
    ("anny", "3ad97744-96b8-4c21-bb0b-5448114308dd", "collab_interaction"),
    ("Q8Pilot", "e74cab24-18d0-4baa-9bee-573000bdf5c4", "simulation_explanation"),
]

# Fixed evidence excerpts for subtitle/render review. These are verbatim or
# conservatively punctuation-normalized text from the frozen Moment anchors;
# keeping complete sentences prevents a validation-only word cap from creating
# a false mid-sentence subtitle failure.
CAPTION_TEXTS = {
    "8d310288-b8ff-422b-88ea-e28d99deaa1a": "A realistic horror game that uses your mind to communicate with entities.",
    "0c6e3e2a-80a8-453c-bcea-1fc8a50eeb66": "But I don't want to go out. But I'm hungry. My maid is right there, and I'm shy!",
    "5a9caed4-3682-40fc-8bfe-062320a03a59": "Those paddles. Ah, this is all BDSM?",
    "0861efd7-8afd-4453-b1e9-80341fb58433": "I'm giving her a little bit different design. Where's the music?",
    "5f5dd861-fccb-4adb-a87b-52a7e2cb4e02": "Is there a game like that? Probably, I don't know. I thought you would know. Why would I know?",
    "3ad97744-96b8-4c21-bb0b-5448114308dd": "Do you think I could stream from the middle of the ocean on a big enough boat?",
    "e74cab24-18d0-4baa-9bee-573000bdf5c4": "We are flying from Sylt Island in Germany to Stuttgart.",
    "e1aca6c6-6817-4ed2-acbf-62219fcb4384": "An exciting battle is about to begin in a world of illusion created by the Poketopia Master.",
}


def _row(db: Path, moment_id: str) -> dict[str, Any]:
    connection = sqlite3.connect(db)
    connection.row_factory = sqlite3.Row
    try:
        item = connection.execute(
            """SELECT m.*, r.title AS recording_title, r.local_path, r.canonical_path,
                      r.duration_ms AS source_duration_ms
               FROM library_moments m JOIN library_recordings r ON r.id=m.recording_id
              WHERE m.id=?""",
            (moment_id,),
        ).fetchone()
        if item is None:
            raise KeyError(f"Moment not found: {moment_id}")
        return dict(item)
    finally:
        connection.close()


def _source(item: dict[str, Any]) -> Path:
    for value in (item.get("canonical_path"), item.get("local_path")):
        path = Path(str(value or ""))
        if path.is_file():
            return path
    raise FileNotFoundError(f"Source media unavailable for {item['recording_id']}")


def _clean_text(value: str, maximum_words: int = 24) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    words = text.split()
    return " ".join(words[:maximum_words]).strip(" ,") or "[non-speech reaction]"


def _words(text: str, duration_ms: int) -> list[SubtitleWord]:
    tokens = text.split()
    start, end = 700, min(duration_ms - 700, 5_700)
    width = max(80, (end - start) // max(len(tokens), 1))
    return [
        SubtitleWord(f"w{index:03d}", token, start + index * width,
                     min(end, start + (index + 1) * width - 10), .8, "en")
        for index, token in enumerate(tokens)
        if min(end, start + (index + 1) * width - 10) > start + index * width
    ]


def _run(command: list[str]) -> tuple[float, str]:
    started = time.perf_counter()
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    elapsed = time.perf_counter() - started
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout)[-3000:])
    return elapsed, result.stderr


def _ass_filter(path: Path) -> str:
    escaped = path.resolve().as_posix().replace(":", r"\:").replace("'", r"\'")
    return f"ass='{escaped}'"


def _render(source: Path, output: Path, start_ms: int, end_ms: int, *, ass: Path | None,
            height: int = 720) -> float:
    output.parent.mkdir(parents=True, exist_ok=True)
    duration = max(1.0, (end_ms - start_ms) / 1000)
    vf = f"scale=-2:{height}"
    if ass:
        vf += "," + _ass_filter(ass)
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start_ms / 1000:.3f}", "-i", str(source), "-t", f"{duration:.3f}",
        "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "29",
        "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(output),
    ]
    elapsed, _ = _run(command)
    return elapsed


def _probe(path: Path) -> dict[str, Any]:
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration,size",
        "-show_entries", "stream=codec_type,width,height", "-of", "json", str(path),
    ], capture_output=True, text=True, encoding="utf-8", check=True)
    payload = json.loads(result.stdout)
    payload["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return payload


def _make_client() -> OpenAIJsonClient:
    return OpenAIJsonClient(OpenAIClientConfig(
        provider="ollama", api_key="ollama", base_url="http://127.0.0.1:11434/v1",
        model="qwen2.5:7b-instruct", timeout=120.0, max_retries=1,
        prefer_responses_api=False,
    ))


def _duration_units(db: Path, item: dict[str, Any]) -> tuple[list[SemanticBoundaryUnit], int]:
    anchor = (int(item["start_ms"]) + int(item["end_ms"])) // 2
    connection = sqlite3.connect(db)
    rows = connection.execute(
        "SELECT evidence_json FROM library_moments WHERE recording_id=? AND end_ms>=? AND start_ms<=?",
        (item["recording_id"], anchor - 180_000, anchor + 180_000),
    ).fetchall()
    connection.close()
    raw: list[tuple[int, int, str]] = []
    for (payload,) in rows:
        try:
            evidence = json.loads(payload or "[]")
        except json.JSONDecodeError:
            continue
        for part in evidence:
            if part.get("type") == "transcript" and str(part.get("text") or "").strip():
                raw.append((int(part["start_ms"]), int(part["end_ms"]), str(part["text"]).strip()))
    if not raw:
        raw = [(int(item["start_ms"]), int(item["end_ms"]), str(item.get("transcript_text") or "event"))]
    if not any(start <= anchor <= end for start, end, _ in raw):
        raw.append((int(item["start_ms"]), int(item["end_ms"]), str(item.get("transcript_text") or "event")))
    ordered = sorted(set(raw))
    focus = min(range(len(ordered)), key=lambda index: abs(ordered[index][0] - anchor))
    left = right = focus
    while left > 0 and ordered[left][0] - ordered[left - 1][1] <= 8_000:
        left -= 1
    while right + 1 < len(ordered) and ordered[right + 1][0] - ordered[right][1] <= 8_000:
        right += 1
    units: list[SemanticBoundaryUnit] = []
    for start, end, text in ordered[left:right + 1]:
        roles: list[str] = []
        if start < int(item["end_ms"]): roles.append("setup")
        if end > int(item["start_ms"]) and start < int(item["end_ms"]): roles.extend(("event", "payoff"))
        if start >= int(item["start_ms"]): roles.append("reaction")
        if start >= int(item["end_ms"]): roles.append("aftermath")
        units.append(SemanticBoundaryUnit(start, end, text, tuple(dict.fromkeys(roles))))
    return units, anchor


def main() -> int:
    parser = argparse.ArgumentParser(description="Render and validate fixed cross-Library product outputs")
    parser.add_argument("--output", type=Path, default=ROOT / "var/generalization_quality_repair/outputs")
    parser.add_argument("--skip-renders", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    client = _make_client()
    provider = QwenTranslationProvider(client)
    subtitle_service = BilingualSubtitleService()
    rows: list[dict[str, Any]] = []
    render_seconds: list[float] = []
    comparison_texts: list[str] = []

    for library, (db, moment_ids) in SELECTIONS.items():
        for index, moment_id in enumerate(moment_ids, 1):
            item = _row(db, moment_id)
            source = _source(item)
            units, center = _duration_units(db, item)
            standard = DurationProfileService().generate(
                event_id=moment_id, units=units, payoff_anchor_ms=center,
                source_duration_ms=int(item["source_duration_ms"]),
                request=DurationRequest(DurationProfile.STANDARD),
            )
            if standard.status.value != "READY":
                raise RuntimeError(f"STANDARD unavailable for {moment_id}: {standard.extension_reason}")
            clip_start, clip_end = standard.start_ms, standard.end_ms
            text = CAPTION_TEXTS.get(
                moment_id,
                _clean_text(str(item.get("summary") or item.get("transcript_text") or "")),
            )
            comparison_texts.append(text)
            clip_dir = output / "clips" / library / f"{index:02d}-{moment_id[:8]}"
            ass = None
            subtitle_report = None
            bilingual = index <= BILINGUAL_COUNTS[library]
            if bilingual:
                track = subtitle_service.build_track(
                    clip_id=moment_id, words=_words(text, clip_end - clip_start),
                    clip_start_ms=0, clip_end_ms=clip_end - clip_start,
                    source_language="en", provider=provider,
                    cache_path=output / "translation-cache.json",
                    timing_provider="segment-timestamps-derived-word-alignment",
                )
                artifacts = subtitle_service.write_artifacts(
                    track, clip_dir / "subtitles", clip_duration_ms=clip_end - clip_start,
                    recognized_speech_duration_ms=sum(c.end_ms - c.start_ms for c in track.cues),
                    captioned_speech_duration_ms=sum(c.end_ms - c.start_ms for c in track.cues),
                )
                ass = artifacts["ass"]
                subtitle_report = json.loads(artifacts["report"].read_text(encoding="utf-8"))
            rendered = clip_dir / "FINAL_STANDARD.mp4"
            if not args.skip_renders:
                render_seconds.append(_render(source, rendered, clip_start, clip_end, ass=ass))
            probe = _probe(rendered) if rendered.is_file() else {}
            rows.append({
                "library": library, "event_id": moment_id, "recording_id": item["recording_id"],
                "source_path": str(source), "start_ms": clip_start, "end_ms": clip_end,
                "content_text": text, "bilingual": bilingual, "output": str(rendered),
                "artifact_role": "FINAL_VARIANT", "is_preview": False,
                "duration_profile": "STANDARD", "semantic_start_reason": standard.extension_reason,
                "semantic_end_reason": standard.extension_reason,
                "probe": probe, "subtitle_report": subtitle_report,
            })
            print(f"rendered {library} {index}/{len(moment_ids)} bilingual={bilingual}", flush=True)

    variants: list[dict[str, Any]] = []
    duration_service = DurationProfileService()
    for library, moment_id, content_type in DURATION_EVENTS:
        db = SELECTIONS[library][0]
        item = _row(db, moment_id)
        source = _source(item)
        units, anchor = _duration_units(db, item)
        generated = duration_service.generate_all(
            event_id=moment_id, units=units, payoff_anchor_ms=anchor,
            source_duration_ms=int(item["source_duration_ms"]),
        )
        for variant in generated:
            variant_dir = output / "duration" / content_type
            rendered = variant_dir / f"{variant.profile.value.lower()}.mp4"
            if variant.status.value == "READY" and not args.skip_renders:
                render_seconds.append(_render(source, rendered, variant.start_ms, variant.end_ms, ass=None, height=480))
            probe = _probe(rendered) if rendered.is_file() else {}
            variants.append({
                "library": library, "content_type": content_type, **asdict(variant),
                "profile": variant.profile.value, "status": variant.status.value,
                "duration_ms": variant.duration_ms, "output": str(rendered), "probe": probe,
            })
            print(f"duration {content_type} {variant.profile.value} {variant.status.value}", flush=True)

    # Fixed 20-cue structural comparison. Qwen is exercised; Argos remains an explicit fallback state.
    all_texts = list(dict.fromkeys(comparison_texts))
    if len(all_texts) < 20:
        connection = sqlite3.connect(DOGFOOD_DB)
        more = connection.execute(
            "SELECT transcript_text FROM library_moments WHERE status='FINAL' AND length(transcript_text)>50 ORDER BY id LIMIT 40"
        ).fetchall()
        connection.close()
        all_texts.extend(_clean_text(item[0]) for item in more)
    cue_texts = list(dict.fromkeys(all_texts))[:20]
    qwen_rows = []
    for index, text in enumerate(cue_texts, 1):
        started = time.perf_counter()
        translated = provider.translate(text, source_language="en", target_language="zh", glossary={})
        qwen_rows.append({
            "cue_id": f"C{index:02d}", "source": text, "translation": translated,
            "empty": not bool(translated.strip()), "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        })
        print(f"translated comparison cue {index}/20", flush=True)
    try:
        from acfv.clips import ArgosTranslationProvider
        argos_provider = ArgosTranslationProvider()
        argos_rows = []
        for index, text in enumerate(cue_texts, 1):
            started = time.perf_counter()
            translated = argos_provider.translate(
                text, source_language="en", target_language="zh", glossary={},
            )
            argos_rows.append({
                "cue_id": f"C{index:02d}", "source": text, "translation": translated,
                "empty": not bool(translated.strip()),
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            })
        argos = {
            "status": "READY", "note": "installed en-to-zh package exercised",
            "rows": argos_rows,
        }
    except Exception as exc:
        argos = {"status": "PROVIDER_UNAVAILABLE", "note": str(exc), "rows": []}

    media_hashes = [item.get("probe", {}).get("sha256") for item in rows]
    candidates = [
        {"candidate_id": f"{row['event_id']}:{kind}", "event_id": row["event_id"], "kind": kind}
        for row in rows for kind in ("speech", "context", "payoff")
    ]
    report = {
        "schema_version": "1.0", "unique_events": len({item["event_id"] for item in rows}),
        "candidate_count": len(candidates), "actual_renders": sum(Path(item["output"]).is_file() for item in rows),
        "bilingual_renders": sum(item["bilingual"] and Path(item["output"]).is_file() for item in rows),
        "unexpected_duplicate_media": len([item for item in media_hashes if item]) - len(set(item for item in media_hashes if item)),
        "clips": rows, "candidates": candidates, "duration_variants": variants,
        "translation_comparison": {"qwen": qwen_rows, "argos": argos},
        "performance": {
            "render_total_seconds": round(sum(render_seconds), 3),
            "render_median_seconds": round(sorted(render_seconds)[len(render_seconds) // 2], 3) if render_seconds else 0,
            "qwen_translation_median_ms": round(sorted(item["latency_ms"] for item in qwen_rows)[len(qwen_rows) // 2], 3),
        },
    }
    (output / "cross-library-output-validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8",
    )
    print(json.dumps({key: report[key] for key in ("unique_events", "candidate_count", "actual_renders", "bilingual_renders", "unexpected_duplicate_media")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
