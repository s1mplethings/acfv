#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utility: Generate ratings.json (and optional ACFV jsonl) from a transcription.json.

Why: Provide a lightweight, dependency-free path to ensure every segment gets a
rating entry, useful for tests and CI without invoking the heavy pipeline.

Input (transcription.json):
	[
	  {"start": 0.0, "end": 5.2, "text": "..."},
	  {"start": 5.2, "end": 9.9, "text": "..."},
	  ...
	]

Output (ratings.json):
	{
	  "clip_001_0.0s-5.2s.mp4": {
		"rating": 0.0, "start": 0.0, "end": 5.2, "duration": 5.2,
		"text": "...", "segment_index": 1
	  },
	  ...
	}

Optional ACFV export (acfv_ratings.jsonl): one JSON object per line with
fields: file, start, end, duration, score, text.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import List, Dict, Any


def _round1(x: float) -> float:
	"""Round to 1 decimal for filename consistency with other modules."""
	try:
		return float(f"{float(x):.1f}")
	except Exception:
		return float(x or 0.0)


def load_transcription(transcription_path: str) -> List[Dict[str, Any]]:
	if not os.path.exists(transcription_path):
		raise FileNotFoundError(f"transcription not found: {transcription_path}")
	with open(transcription_path, "r", encoding="utf-8") as f:
		data = json.load(f)
		if not isinstance(data, list):
			raise ValueError("transcription.json must be a list of segments")
		return data


def make_clip_name(index: int, start: float, end: float) -> str:
	s = _round1(start)
	e = _round1(end)
	return f"clip_{index:03d}_{s:.1f}s-{e:.1f}s.mp4"


def generate_ratings_from_transcription(
	transcription_path: str,
	ratings_path: str,
	default_rating: float = 0.0,
	write_acfv_jsonl: bool = False,
) -> Dict[str, Dict[str, Any]]:
	"""Generate ratings.json mapping each segment to an entry.

	- Ensures every transcription segment yields exactly one rating record.
	- Uses default_rating for score unless overridden later by other tools.
	- Optionally writes ACFV jsonl alongside ratings.json.

	Returns the ratings dict written.
	"""
	segments = load_transcription(transcription_path)

	ratings: Dict[str, Dict[str, Any]] = {}
	for i, seg in enumerate(segments, start=1):
		start = float(seg.get("start", 0.0))
		end = float(seg.get("end", 0.0))
		if end < start:
			# swap to be safe in edge cases
			start, end = end, start
		duration = max(0.0, end - start)
		text = (seg.get("text") or "").strip()
		name = make_clip_name(i, start, end)
		ratings[name] = {
			"rating": float(default_rating),
			"start": start,
			"end": end,
			"duration": duration,
			"text": text,
			"segment_index": i,
		}

	os.makedirs(os.path.dirname(ratings_path) or ".", exist_ok=True)
	with open(ratings_path, "w", encoding="utf-8") as f:
		json.dump(ratings, f, ensure_ascii=False, indent=2)

	if write_acfv_jsonl:
		out_dir = os.path.dirname(ratings_path) or "."
		jsonl_path = os.path.join(out_dir, "acfv_ratings.jsonl")
		with open(jsonl_path, "w", encoding="utf-8") as f:
			for file_name, data in ratings.items():
				rec = {
					"file": file_name,
					"start": float(data.get("start", 0.0)),
					"end": float(data.get("end", 0.0)),
					"duration": float(data.get("duration", 0.0)),
					"score": float(data.get("rating", 0.0)),
					"text": data.get("text", ""),
				}
				f.write(json.dumps(rec, ensure_ascii=False) + "\n")

	return ratings


def main():
	parser = argparse.ArgumentParser(description="Generate ratings.json from transcription.json")
	parser.add_argument("--save-dir", default="save", help="Directory containing transcription.json; outputs written here")
	parser.add_argument("--default-rating", type=float, default=0.0, help="Default rating for each segment")
	parser.add_argument("--acfv", action="store_true", help="Also write acfv_ratings.jsonl")
	args = parser.parse_args()

	save_dir = args.save_dir
	transcription_path = os.path.join(save_dir, "transcription.json")
	ratings_path = os.path.join(save_dir, "ratings.json")

	ratings = generate_ratings_from_transcription(
		transcription_path,
		ratings_path,
		default_rating=args.default_rating,
		write_acfv_jsonl=args.acfv,
	)
	print(f"Wrote ratings for {len(ratings)} segments to {ratings_path}")


if __name__ == "__main__":
	main()

