#!/usr/bin/env python3
"""Evaluate a user-filled ACFV ASR ground-truth CSV; never infers labels."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--pack", type=Path, default=None)
    args = parser.parse_args()
    try:
        from jiwer import cer, wer
    except ImportError as exc:
        raise SystemExit("JiWER is required only for evaluation: python -m pip install jiwer") from exc
    pack = args.pack or args.csv.parent
    rows = list(csv.DictReader(args.csv.open(encoding="utf-8-sig")))
    missing = [row["sample_id"] for row in rows if not str(row.get("human_transcript") or "").strip()]
    if missing:
        raise SystemExit(f"Ground truth is incomplete ({len(missing)} blank rows); WER is not claimed")
    references, hypotheses = [], []
    details = []
    for row in rows:
        sample = pack / row["sample_id"]
        hypothesis = (sample / "final.txt").read_text(encoding="utf-8").strip()
        reference = row["human_transcript"].strip()
        references.append(reference)
        hypotheses.append(hypothesis)
        metadata = json.loads((sample / "metadata.json").read_text(encoding="utf-8"))
        details.append({**metadata, "reference": reference, "hypothesis": hypothesis,
                        "WER": wer(reference, hypothesis), "CER": cer(reference, hypothesis)})
    result = {"samples": len(rows), "WER": wer(references, hypotheses),
              "CER": cer(references, hypotheses), "samples_detail": details}
    output = args.csv.with_name("asr-ground-truth-evaluation.json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
