from __future__ import annotations

import csv
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from .analysis import HumanReviewAnalysis
from .repository import HumanReviewRepository


class HumanReviewExporter:
    def __init__(self, repository: HumanReviewRepository) -> None:
        self.repository = repository

    def export(self, output_root: Path) -> dict[str, Path]:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = Path(output_root).resolve() / f"human-review-{stamp}"
        target.mkdir(parents=True, exist_ok=False)
        rows = self.repository.annotation_rows()
        metadata = self.repository.dataset_metadata()
        analysis = HumanReviewAnalysis(self.repository).calculate()
        json_path = target / "annotations.json"
        json_path.write_text(
            json.dumps({"metadata": metadata, "annotations": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        csv_path = target / "annotations.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            fields = ["sample_id", "task", "creator", "content_type", "status", "answer_json", "note", "revisit", "updated_at"]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    "sample_id": row["sample_id"], "task": row["task"], "creator": row["creator"],
                    "content_type": row["content_type"], "status": row["status"],
                    "answer_json": json.dumps(row["answer"], ensure_ascii=False, sort_keys=True),
                    "note": row["note"], "revisit": int(row["revisit"]), "updated_at": row["updated_at"],
                })
        analysis_json = target / "analysis.json"
        analysis_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        analysis_md = target / "analysis.md"
        lines = ["# Human Review Analysis", "", f"Dataset: `{metadata.get('dataset_version', 'unknown')}`", ""]
        for task, summary in analysis.items():
            lines.extend([f"## {task.title()}", "", f"Reviewed: {summary.get('reviewed', 0)}", f"Status: {summary.get('maturity', 'Not enough data')}", "", "```json", json.dumps(summary, ensure_ascii=False, indent=2), "```", ""])
        analysis_md.write_text("\n".join(lines), encoding="utf-8")
        return {"folder": target, "csv": csv_path, "json": json_path, "analysis": analysis_md, "analysis_json": analysis_json}
