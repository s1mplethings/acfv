from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
import sqlite3
import statistics
import subprocess
import time
import zipfile
import sys


ROOT = Path(__file__).resolve().parents[1]
DOGFOOD_DB = ROOT / "var/intelligence_quality_20261008/library_v2.db"
Q8_DB = ROOT / "var/cross_library_generalization/q8-library.db"

SELECTIONS = {
    "Saruei": (DOGFOOD_DB, [
        "8d310288-b8ff-422b-88ea-e28d99deaa1a", "0c6e3e2a-80a8-453c-bcea-1fc8a50eeb66",
        "0e04994c-e1f1-4875-bd8b-d618f1892353",
    ], 10),
    "anny": (DOGFOOD_DB, [
        "5a9caed4-3682-40fc-8bfe-062320a03a59", "0861efd7-8afd-4453-b1e9-80341fb58433",
        "5f5dd861-fccb-4adb-a87b-52a7e2cb4e02", "3ad97744-96b8-4c21-bb0b-5448114308dd",
        "877e635c-552d-40d8-bab8-cd8fa4756eff",
    ], 15),
    "Q8_Holdout": (Q8_DB, [
        "e74cab24-18d0-4baa-9bee-573000bdf5c4", "7c47cf07-ff34-4eb5-bc45-18b822148c12",
    ], 5),
}

MODELS = {
    "current_medium.txt": "medium",
    "candidate_distil_large_v3.txt": "distil-large-v3",
    "candidate_large_v3_turbo.txt": "large-v3-turbo",
    "optional_large_v3.txt": "large-v3",
}


def _activate_windows_cuda_runtime() -> None:
    if os.name != "nt":
        return
    runtime = Path(sys.prefix) / "Library" / "bin"
    if runtime.is_dir():
        os.environ["PATH"] = str(runtime) + os.pathsep + os.environ.get("PATH", "")
        add_directory = getattr(os, "add_dll_directory", None)
        if callable(add_directory):
            add_directory(str(runtime))


def _moment(db: Path, moment_id: str) -> dict:
    connection = sqlite3.connect(db)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """SELECT m.*, r.local_path, r.canonical_path, r.title AS recording_title,
                      r.duration_ms AS source_duration_ms
                 FROM library_moments m JOIN library_recordings r ON r.id=m.recording_id
                WHERE m.id=?""", (moment_id,),
        ).fetchone()
        if row is None:
            raise KeyError(moment_id)
        return dict(row)
    finally:
        connection.close()


def _source(row: dict) -> Path:
    for value in (row.get("canonical_path"), row.get("local_path")):
        path = Path(str(value or ""))
        if path.is_file():
            return path
    raise FileNotFoundError(row["recording_id"])


def _extract(source: Path, output: Path, start_ms: int, end_ms: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{start_ms / 1000:.3f}",
        "-i", str(source), "-t", f"{(end_ms - start_ms) / 1000:.3f}", "-vn", "-ac", "1",
        "-ar", "16000", "-c:a", "pcm_s16le", str(output),
    ], check=True)


def _prepare(root: Path) -> list[dict]:
    samples: list[dict] = []
    for creator, (db, ids, count) in SELECTIONS.items():
        rows = [_moment(db, item) for item in ids]
        for index in range(count):
            row = rows[index % len(rows)]
            center = (int(row["start_ms"]) + int(row["end_ms"])) // 2 + (-7_000, 0, 7_000)[index % 3]
            duration = (12_000, 18_000, 24_000)[index % 3]
            start = max(0, center - duration // 2)
            end = min(int(row["source_duration_ms"]), start + duration)
            sample_id = f"{len(samples) + 1:02d}-{creator}-{row['id'][:8]}-{index // len(rows) + 1}"
            target = root / sample_id
            audio = target / "audio.wav"
            _extract(_source(row), audio, start, end)
            metadata = {
                "sample_id": sample_id, "creator": creator, "recording": row["recording_id"],
                "recording_title": row["recording_title"], "moment_id": row["id"],
                "start_ms": start, "end_ms": end, "duration_seconds": (end - start) / 1000,
                "content_type": "HUMAN_REVIEW_REQUIRED",
                "audio_condition": "HUMAN_REVIEW_REQUIRED",
                "source_excerpt": str(row.get("transcript_text") or row.get("summary") or ""),
            }
            (target / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            samples.append({"dir": target, "audio": audio, "metadata": metadata})
    return samples


def _transcribe(samples: list[dict], model_name: str, filename: str, *, device: str) -> dict:
    if all((item["dir"] / filename).is_file() and not (item["dir"] / filename).read_text(
            encoding="utf-8").startswith("[MODEL_") for item in samples):
        return {"model": model_name, "reused": True, "successes": len(samples), "failures": []}
    import torch
    from faster_whisper import WhisperModel

    compute = "float16" if device == "cuda" else "int8"
    started_load = time.perf_counter()
    model = WhisperModel(model_name, device=device, compute_type=compute)
    load_seconds = time.perf_counter() - started_load
    timings: list[float] = []
    failures: list[str] = []
    for item in samples:
        started = time.perf_counter()
        try:
            segments, info = model.transcribe(
                str(item["audio"]), language="en", word_timestamps=True, vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500}, condition_on_previous_text=True,
            )
            material = list(segments)
            text = " ".join(str(segment.text).strip() for segment in material if str(segment.text).strip())
            elapsed = time.perf_counter() - started
            timings.append(elapsed)
            (item["dir"] / filename).write_text(text, encoding="utf-8")
            meta_path = item["dir"] / "metadata.json"
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            metadata.setdefault("models", {})[model_name] = {
                "wall_time_seconds": round(elapsed, 3), "rtf": round(elapsed / metadata["duration_seconds"], 4),
                "detected_language": getattr(info, "language", None), "word_timestamps": True,
                "vad_filter": True, "status": "READY",
            }
            meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            failures.append(f"{item['metadata']['sample_id']}: {exc}")
            (item["dir"] / filename).write_text(f"[MODEL_FAILURE] {exc}", encoding="utf-8")
    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()
    return {
        "model": model_name, "load_seconds": round(load_seconds, 3),
        "median_seconds": round(statistics.median(timings), 3) if timings else None,
        "median_rtf": round(statistics.median(
            elapsed / samples[index]["metadata"]["duration_seconds"] for index, elapsed in enumerate(timings)
        ), 4) if len(timings) == len(samples) else None,
        "successes": len(timings), "failures": failures,
    }


def _review(root: Path, results: list[dict]) -> None:
    lines = [
        "# ASR Side-by-side Review", "",
        "No model is pre-declared as correct. No WER is asserted without human ground truth.", "",
    ]
    for sample in sorted(path for path in root.iterdir() if path.is_dir()):
        metadata = json.loads((sample / "metadata.json").read_text(encoding="utf-8"))
        lines.extend([f"## {metadata['sample_id']}", "", f"- Creator: {metadata['creator']}",
                      f"- Recording: {metadata['recording']}",
                      f"- Range: {metadata['start_ms']}–{metadata['end_ms']} ms", ""])
        for filename, model in MODELS.items():
            text = (sample / filename).read_text(encoding="utf-8")
            lines.extend([f"### {model}", "", text, ""])
        lines.extend([
            "BEST: [ ] Current  [ ] Candidate A  [ ] Candidate B", "",
            "ERROR TYPE: [ ] Wrong Word  [ ] Missing Word  [ ] Hallucination  [ ] Proper Noun  [ ] Punctuation  [ ] Speaker Mix  [ ] Music  [ ] Other",
            "", "NOTES:", "", "---", "",
        ])
    (root / "side-by-side-review.md").write_text("\n".join(lines), encoding="utf-8")
    (root / "asr-model-comparison.json").write_text(json.dumps({
        "schema_version": "1.0", "human_review_required": True, "wer": None,
        "models": results, "selection": "PENDING_HUMAN_REVIEW",
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "var/final_clip_quality/asr-quality-review-bundle")
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--models", default=",".join(MODELS.values()),
                        help="Comma-separated model names; omitted models remain explicit NOT_RUN entries")
    args = parser.parse_args()
    _activate_windows_cuda_runtime()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    samples = _prepare(root)
    results = []
    selected = {item.strip() for item in args.models.split(",") if item.strip()}
    for filename, model in MODELS.items():
        if model not in selected:
            results.append({"model": model, "successes": 0, "failures": [], "status": "NOT_RUN"})
            continue
        try:
            results.append(_transcribe(samples, model, filename, device=args.device))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            for item in samples:
                (item["dir"] / filename).write_text(f"[MODEL_UNAVAILABLE] {error}", encoding="utf-8")
            results.append({"model": model, "successes": 0, "failures": [error], "status": "MODEL_UNAVAILABLE"})
    for filename, model in MODELS.items():
        for item in samples:
            path = item["dir"] / filename
            if not path.is_file():
                path.write_text(f"[MODEL_NOT_RUN] {model}", encoding="utf-8")
    _review(root, results)
    archive = root.parent / "asr-quality-review-bundle.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in root.rglob("*"):
            if path.is_file():
                bundle.write(path, path.relative_to(root.parent))
    print(json.dumps({"samples": len(samples), "archive": str(archive), "models": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
