from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a semantic duration plan from an existing word transcript")
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recording-id", required=True)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--clip-start-ms", type=int, required=True)
    parser.add_argument("--source-duration-ms", type=int, required=True)
    parser.add_argument("--payoff-anchor-ms", type=int, required=True)
    parser.add_argument("--event-start-ms", type=int)
    parser.add_argument("--event-end-ms", type=int)
    parser.add_argument("--source-language", default="en")
    args = parser.parse_args()

    data = json.loads(args.transcript.read_text(encoding="utf-8"))
    segments = list(data.get("segments") or [])
    units = []
    words = []
    for segment_index, segment in enumerate(segments):
        start_ms = args.clip_start_ms + round(float(segment["start"]) * 1000)
        end_ms = args.clip_start_ms + round(float(segment["end"]) * 1000)
        if end_ms < args.payoff_anchor_ms:
            roles = ["setup"]
        elif start_ms <= args.payoff_anchor_ms <= end_ms:
            roles = ["event", "payoff"]
        elif start_ms <= args.payoff_anchor_ms + 15_000:
            roles = ["reaction"]
        else:
            roles = ["aftermath"]
        units.append({"start_ms": start_ms, "end_ms": end_ms, "text": str(segment.get("text") or "").strip(), "roles": roles})
        for word_index, word in enumerate(segment.get("words") or []):
            item = dict(word)
            item["word_id"] = f"s{segment_index:04d}w{word_index:04d}"
            item["start_ms"] = args.clip_start_ms + round(float(word["start"]) * 1000)
            item["end_ms"] = args.clip_start_ms + round(float(word["end"]) * 1000)
            item["language"] = args.source_language
            words.append(item)
    if args.event_start_ms is not None and units and args.event_start_ms < units[0]["start_ms"]:
        units.insert(0, {"start_ms": args.event_start_ms, "end_ms": units[0]["start_ms"],
                         "text": "[natural event lead-in]", "roles": ["setup"]})
    if args.event_end_ms is not None and units and args.event_end_ms > units[-1]["end_ms"]:
        units.append({"start_ms": units[-1]["end_ms"], "end_ms": args.event_end_ms,
                      "text": "[natural event settling boundary]", "roles": ["aftermath"]})
    payload = {
        "schema_version": "1.0",
        "recording_id": args.recording_id,
        "event_id": args.event_id,
        "clip_id": args.event_id,
        "source_path": str(args.source.resolve()),
        "source_duration_ms": args.source_duration_ms,
        "payoff_anchor_ms": args.payoff_anchor_ms,
        "source_language": args.source_language,
        "units": units,
        "words": words,
        "glossary": {},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
