from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
import os
from pathlib import Path
import sys
import time

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def contact_sheets(manifest: Path, output: Path, *, limit: int = 64) -> dict[str, str]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for line in manifest.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        groups[str(row.get("creator_id") or "unknown")].append(row)
    result = {}
    for creator, rows in groups.items():
        selected = rows[:limit]
        thumb = 160
        columns = 8
        rows_count = math.ceil(len(selected) / columns)
        sheet = Image.new("RGB", (columns * thumb, rows_count * (thumb + 20)), "#11151d")
        draw = ImageDraw.Draw(sheet)
        for index, row in enumerate(selected):
            image = Image.open(row["crop_path"]).convert("RGB")
            image.thumbnail((thumb, thumb))
            x = (index % columns) * thumb + (thumb - image.width) // 2
            y = (index // columns) * (thumb + 20) + (thumb - image.height) // 2
            sheet.paste(image, (x, y))
            draw.text(((index % columns) * thumb + 4, (index // columns) * (thumb + 20) + thumb + 2), str(row["timestamp_ms"]), fill="white")
        target = output / "contact-sheets" / f"{creator}-probe.jpg"
        target.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(target, quality=88)
        result[creator] = str(target)
    return result


def transcribe(receipts: Path, output: Path) -> dict:
    dll_dir = Path(sys.executable).resolve().parent / "Library" / "bin"
    dll_handle = None
    if os.name == "nt" and dll_dir.is_dir():
        os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")
        dll_handle = os.add_dll_directory(str(dll_dir))
    import torch
    from faster_whisper import WhisperModel

    rows = json.loads(receipts.read_text(encoding="utf-8")).get("rows") or []
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = WhisperModel(
        "Systran/faster-whisper-large-v3", device=device,
        compute_type="float16" if device == "cuda" else "int8", local_files_only=True,
    )
    results = []
    for row in rows:
        started = time.perf_counter()
        segments, info = model.transcribe(
            row["local_path"], beam_size=5, word_timestamps=True, vad_filter=True,
            condition_on_previous_text=False,
        )
        values = list(segments)
        text = " ".join(str(segment.text).strip() for segment in values).strip()
        confidence = [
            max(0.0, min(1.0, math.exp(float(segment.avg_logprob)) * (1 - float(segment.no_speech_prob))))
            for segment in values
        ]
        results.append({
            "creator": row["creator"], "vod_id": row["vod_id"], "duration_ms": row["metadata"]["media_validation"]["duration_ms"],
            "detected_language": info.language, "language_probability": info.language_probability,
            "speech_segments": len(values), "transcript_characters": len(text),
            "mean_engineering_confidence": sum(confidence) / len(confidence) if confidence else 0.0,
            "low_confidence_segments": sum(value < 0.6 for value in confidence),
            "runtime_seconds": time.perf_counter() - started,
            "text_preview": text[:500],
            "segments": [{
                "start_ms": int(segment.start * 1000), "end_ms": int(segment.end * 1000),
                "text": str(segment.text).strip(), "engineering_confidence": confidence[index],
            } for index, segment in enumerate(values)],
            "accent_accuracy": "NOT_EVALUATED_WITHOUT_HUMAN_GROUND_TRUTH",
        })
    report = {
        "schema_version": "1.0", "provider": "faster-whisper-large-v3",
        "device": device, "human_ground_truth": "PENDING", "rows": results,
    }
    write_json(output / "probe-asr-engineering.json", report)
    if dll_handle is not None:
        dll_handle.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipts", type=Path, required=True)
    parser.add_argument("--visual-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contacts = contact_sheets(args.visual_manifest, args.output)
    report = transcribe(args.receipts, args.output)
    write_json(args.output / "probe-analysis-summary.json", {
        "schema_version": "1.0", "contact_sheets": contacts,
        "asr_rows": len(report["rows"]), "human_ground_truth": "PENDING",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
