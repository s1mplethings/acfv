from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from acfv.human_review.dataset import HumanReviewDatasetBuilder
from acfv.human_review.gui import HumanReviewWindow, SettingsDialog, review_stylesheet
from acfv.human_review.models import ReviewTask
from acfv.human_review.repository import HumanReviewRepository


TARGETS = {
    ReviewTask.ASR: 10,
    ReviewTask.IDENTITY: 10,
    ReviewTask.ADAPTIVE_ASR: 0,
    ReviewTask.TRANSLATION: 10,
    ReviewTask.BOUNDARY: 10,
    ReviewTask.WATCHABILITY: 10,
    ReviewTask.SUBTITLE: 10,
    ReviewTask.PUBLISHABILITY: 5,
}


def choose_and_save(window: HumanReviewWindow, task: ReviewTask, count: int) -> list[float]:
    window.open_task(task)
    page = window.review_pages[task]
    save_times: list[float] = []
    for _ in range(count):
        if not page.current:
            raise AssertionError(f"{task.value} queue ended early")
        if task == ReviewTask.BOUNDARY:
            page.choice_buttons[1].click()
            page.choice_buttons[4].click()
            page.choice_buttons[7].click()
        else:
            page.choice_buttons[0].click()
        before = time.perf_counter(); page.save(); save_times.append((time.perf_counter() - before) * 1000)
        QApplication.processEvents()
    return save_times


def screenshot(window: HumanReviewWindow, output: Path, name: str) -> None:
    QApplication.processEvents()
    if not window.grab().save(str(output / f"{name}.png")):
        raise RuntimeError(f"failed to save screenshot {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--annotate", action="store_true")
    args = parser.parse_args()
    output = args.output_root.resolve(); output.mkdir(parents=True, exist_ok=True)
    application = QApplication.instance() or QApplication([])
    application.setApplicationName("ACFV Human Review Lab")
    application.setStyleSheet(review_stylesheet())
    repository = HumanReviewRepository(output / "human_review_test.sqlite", backup_dir=output / "backups")
    result = HumanReviewDatasetBuilder(args.source_root).build()
    repository.replace_dataset(result.samples, result.metadata)
    startup = time.perf_counter(); window = HumanReviewWindow(repository, source_root=args.source_root, output_root=output / "exports")
    width, height = (1280, 720) if args.scale > 1.0 else (1920, 1080)
    window.resize(width, height); window.show(); QApplication.processEvents()
    timings: dict[str, float] = {}
    timings["startup_ms"] = (time.perf_counter() - startup) * 1000
    start = time.perf_counter(); window.refresh_analysis(); timings["analysis_refresh_ms"] = (time.perf_counter() - start) * 1000
    window.show_page("overview"); screenshot(window, output, "01-overview")
    page_map = (
        (ReviewTask.ASR, "02-asr"), (ReviewTask.IDENTITY, "03-identity"),
        (ReviewTask.TRUSTED_SPEECH, "04-trusted-speech"),
        (ReviewTask.ADAPTIVE_ASR, "05-adaptive-asr"), (ReviewTask.TRANSLATION, "06-translation"),
        (ReviewTask.BOUNDARY, "07-boundary"), (ReviewTask.WATCHABILITY, "08-watchability"),
        (ReviewTask.SUBTITLE, "09-subtitle"), (ReviewTask.PUBLISHABILITY, "10-publishability"),
    )
    for task, name in page_map:
        before = time.perf_counter(); window.open_task(task); QApplication.processEvents(); timings[f"switch_{task.value}_ms"] = (time.perf_counter() - before) * 1000; screenshot(window, output, name)
        page = window.review_pages[task]
        if page.current and page.current.media_a:
            before = time.perf_counter(); page.player.load(page.current.media_a, position_ms=page.current.start_ms); QApplication.processEvents(); timings[f"media_load_{task.value}_ms"] = (time.perf_counter() - before) * 1000
    window.show_page("analysis"); screenshot(window, output, "11-analysis")
    window.open_task(ReviewTask.ASR); screenshot(window, output, "12-filters")
    settings = SettingsDialog(window.settings, window); settings.show(); QApplication.processEvents();
    if not settings.grab().save(str(output / "13-settings.png")): raise RuntimeError("failed settings screenshot")
    settings.close()
    if args.annotate:
        all_save_times: list[float] = []
        for task, count in TARGETS.items():
            before = time.perf_counter(); values = choose_and_save(window, task, count); timings[f"annotate_{task.value}_{count}_ms"] = (time.perf_counter() - before) * 1000; all_save_times.extend(values)
        timings["save_next_average_ms"] = sum(all_save_times) / len(all_save_times)
        timings["save_next_p95_ms"] = sorted(all_save_times)[max(0, round(len(all_save_times) * 0.95) - 1)]
        if timings["save_next_average_ms"] >= 100:
            raise AssertionError(f"Save & Next average regressed: {timings['save_next_average_ms']:.1f} ms")
        if timings["save_next_p95_ms"] >= 150:
            raise AssertionError(f"Save & Next p95 regressed: {timings['save_next_p95_ms']:.1f} ms")
    counts_before = {item.task.value: item.completed for item in repository.progress()}
    window.close(); QApplication.processEvents()
    reopened = HumanReviewRepository(output / "human_review_test.sqlite", backup_dir=output / "backups")
    counts_after = {item.task.value: item.completed for item in reopened.progress()}
    if counts_before != counts_after:
        raise AssertionError("restart persistence mismatch")
    receipt = {
        "dataset": result.metadata,
        "counts": result.counts,
        "annotations_before_restart": counts_before,
        "annotations_after_restart": counts_after,
        "integrity": reopened.integrity_check(),
        "duplicate_sample_ids": len(result.samples) - len({item.sample_id for item in result.samples}),
        "formal_pair_count": sum(bool(item.private.get("pair_id")) for item in result.samples),
        "unique_formal_pair_count": len({(item.task.value, item.private.get("pair_id")) for item in result.samples if item.private.get("pair_id")}),
        "consistency_controls": sum(item.consistency_control for item in result.samples),
        "timings": timings,
        "scale": args.scale,
        "resolution": [width, height],
        "production_db_touched": False,
    }
    (output / "native-validation.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
