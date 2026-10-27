"""Native Qt real-library validation for the workflow-oriented product GUI."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from acfv.product_gui.backend import ProductBackend
from acfv.product_gui.models import OBJECT_ROLE
from acfv.product_gui.shell import ProductMainWindow


def wait_for(app: QApplication, predicate, *, timeout_ms: int = 60_000, label: str = "condition") -> float:
    started = time.perf_counter()
    while (time.perf_counter() - started) * 1000 < timeout_ms:
        app.processEvents()
        if predicate():
            return round(time.perf_counter() - started, 4)
        QTest.qWait(25)
    raise TimeoutError(f"Timed out waiting for {label}")


def capture(app: QApplication, window: ProductMainWindow, path: Path, width: int, height: int) -> None:
    window.resize(width, height)
    app.processEvents(); QTest.qWait(120); app.processEvents()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not window.grab().save(str(path), "PNG"):
        raise RuntimeError(f"Could not save screenshot: {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--index-root", type=Path, required=True)
    parser.add_argument("--clip-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--visual-only", action="store_true")
    parser.add_argument("--import-media", type=Path)
    parser.add_argument("--import-only", action="store_true")
    args = parser.parse_args()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("ACFV GUI Validation")
    backend = ProductBackend(db_path=args.db, index_root=args.index_root, clip_root=args.clip_root)
    window = ProductMainWindow(backend=backend)
    window.show()
    timings: dict[str, float] = {}
    workflows: list[dict] = []
    screenshots = args.output / "screenshots"
    started = time.perf_counter()
    timings["shell_visible"] = wait_for(app, lambda: window.isVisible(), label="shell visible")
    timings["library_ready"] = wait_for(
        app,
        lambda: window.creator_model.rowCount() > 0 and window.library_page.recording_model.rowCount() > 0,
        label="real library",
    )
    timings["first_thumbnail"] = wait_for(
        app,
        lambda: bool(window.library_page.recording_model._thumbnails),
        timeout_ms=30_000,
        label="first async thumbnail",
    )
    window.navigate("library")
    capture(app, window, screenshots / "01-library.png", 1920, 1080)
    capture(app, window, screenshots / "01-library-1280x720.png", 1280, 720)
    capture(app, window, screenshots / "01-library-2560x1440.png", 2560, 1440)

    if args.visual_only:
        result = {
            "result": "PASS",
            "visual_only": True,
            "device_pixel_ratio": app.primaryScreen().devicePixelRatio(),
            "screen": app.primaryScreen().size().width(),
            "timings": timings,
            "screenshots": sorted(str(path) for path in screenshots.glob("*.png")),
        }
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "native-validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        window.close(); app.processEvents()
        return 0

    if args.import_media:
        imported_rows = []
        window.library_controller.imported.connect(imported_rows.append)
        window.library_controller.import_local(
            str(args.import_media.resolve()),
            window.context.creator.id,
        )
        timings["local_import_registered"] = wait_for(
            app, lambda: bool(imported_rows), timeout_ms=120_000, label="local import registration"
        )
        imported = imported_rows[-1]
        if not imported.job_id:
            raise RuntimeError("Imported Recording did not expose its canonical processing job")
        timings["local_import_processed"] = wait_for(
            app,
            lambda: (
                imported.job_id in window.activity._jobs
                and window.activity._jobs[imported.job_id].state in {"已完成", "失败", "已取消"}
            ),
            timeout_ms=900_000,
            label="local import backend processing",
        )
        job = window.activity._jobs[imported.job_id]
        workflows.append({
            "step": "local_import_and_process",
            "recording_id": imported.id,
            "job_id": imported.job_id,
            "job_state": job.state,
            "result": "PASS" if job.state == "已完成" else "FAIL",
        })
        capture(app, window, screenshots / "11-local-import-job.png", 1920, 1080)
        if args.import_only:
            window.navigate("search")
            window.search_page.query.setText("Okay anyways nobody here")
            window.search_page.run_search()
            timings["post_import_search"] = wait_for(
                app,
                lambda: window.search_page.results.model.rowCount() > 0,
                timeout_ms=120_000,
                label="post-import search",
            )
            workflows.append({
                "step": "search_after_processing",
                "results": window.search_page.results.model.rowCount(),
                "result": "PASS",
            })
            capture(app, window, screenshots / "12-post-import-search.png", 1920, 1080)
            result = {
                "result": "PASS" if all(item["result"] == "PASS" for item in workflows) else "FAIL",
                "device_pixel_ratio": app.primaryScreen().devicePixelRatio(),
                "timings": timings,
                "workflows": workflows,
                "screenshots": sorted(str(path) for path in screenshots.glob("*.png")),
            }
            args.output.mkdir(parents=True, exist_ok=True)
            (args.output / "native-validation.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            window.close(); app.processEvents()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["result"] == "PASS" else 1

    recording_index = window.library_page.recording_model.index(0, 0)
    recording = recording_index.data(OBJECT_ROLE)
    window.library_page._open_recording(recording_index)
    timings["recording_workspace"] = wait_for(
        app, lambda: window.library_page.workspace.recording is not None, label="recording workspace"
    )
    capture(app, window, screenshots / "02-recording.png", 1920, 1080)
    workflows.append({"step": "open_recording", "recording_id": recording.id, "result": "PASS"})

    window.navigate("search")
    window.search_page.query.setText("Okay anyways there's nobody here can't")
    before = time.perf_counter(); window.search_page.run_search()
    window.activity_bar.view.setVisible(True)
    capture(app, window, screenshots / "09-jobs.png", 1920, 1080)
    timings["search"] = wait_for(
        app, lambda: window.search_page.results.model.rowCount() > 0, timeout_ms=90_000, label="search results"
    )
    timings["search_wall"] = round(time.perf_counter() - before, 4)
    capture(app, window, screenshots / "03-search.png", 1920, 1080)
    search_result = window.search_page.results.model.rows[0]
    workflows.append({"step": "search", "query": window.search_page.query.text(), "results": window.search_page.results.model.rowCount(), "result": "PASS"})

    window.open_event(search_result)
    wait_for(app, lambda: window.current_page_name() == "event", label="event view")
    capture(app, window, screenshots / "05-event.png", 1920, 1080)

    window.navigate("conversation")
    question = "Okay anyways nobody here cannot go over this"
    window.conversation_page.query.setPlainText(question)
    before = time.perf_counter(); window.conversation_page.ask()
    timings["conversation"] = wait_for(
        app,
        lambda: bool(window.conversation_page.answer.text()),
        timeout_ms=90_000,
        label="conversation answer",
    )
    timings["conversation_wall"] = round(time.perf_counter() - before, 4)
    capture(app, window, screenshots / "04-conversation.png", 1920, 1080)
    workflows.append({
        "step": "conversation",
        "question": question,
        "evidence": window.conversation_page.evidence.model.rowCount(),
        "mode": window.conversation_page.mode.text(),
        "result": "PASS",
    })

    # Workflow #2: supported conversation -> evidence -> proposed Clip -> Reject.
    evidence = window.conversation_page.evidence.model.rows[0]
    previous_clip_id = window.review_page.current_clip_id
    window.conversation_controller.create_clip(evidence.id, question)
    wait_for(
        app,
        lambda: bool(window.review_page.current_clip_id) and window.review_page.current_clip_id != previous_clip_id
        and window.review_page.workflow is not None,
        label="conversation clip review",
    )
    conversation_clip_id = window.review_page.current_clip_id
    window.review_controller.decide(window.review_page.workflow, "REJECTED", "Validation workflow")
    wait_for(app, lambda: window.review_page.status.text() == "已拒绝", label="reject decision")
    workflows.append({
        "step": "conversation_evidence_clip_reject",
        "clip_id": conversation_clip_id,
        "evidence_moment_id": evidence.id,
        "result": "PASS",
    })

    window.navigate("review")
    window.review_page.refresh(None)
    wait_for(app, lambda: window.review_page.clip_model.rowCount() >= 8, label="eight clips")
    reviewed = []
    for position in range(window.review_page.clip_model.rowCount()):
        clip = window.review_page.clip_model.rows[position]
        window.review_page.workflow = None
        window.review_page.open_clip(clip.id)
        wait_for(app, lambda: window.review_page.workflow is not None and window.review_page.current_clip_id == clip.id, label=f"review {clip.id}")
        reviewed.append({
            "clip_id": clip.id,
            "review_status": clip.review_status,
            "variants": {name: row.status for name, row in window.review_page._variants.items()},
            "cue_count": window.review_page.cues.rowCount(),
            "warning_count": window.review_page.warnings.count(),
        })
    first = next((item for item in window.review_page.clip_model.rows if item.moment_id == "c93fe2ca-4dfe-4d77-9dc7-5effc38e3f65"), window.review_page.clip_model.rows[0])
    window.review_page.workflow = None; window.review_page.open_clip(first.id)
    wait_for(app, lambda: window.review_page.workflow is not None and window.review_page.current_clip_id == first.id, label="representative review")
    capture(app, window, screenshots / "06-review-standard.png", 1920, 1080)
    capture(app, window, screenshots / "07-review-warning.png", 1280, 720)
    if window.review_page.cues.rowCount():
        zh = window.review_page.cues.item(0, 1)
        en = window.review_page.cues.item(0, 2)
        zh.setText(zh.text().rstrip("。") + "。")
        en.setText(en.text().rstrip(".") + ".")
        window.review_page.save_cues()
        wait_for(app, lambda: not window.review_page._dirty, label="subtitle save")
        capture(app, window, screenshots / "08-subtitle-editor.png", 1920, 1080)
        workflows.append({"step": "edit_bilingual_cue", "clip_id": first.id, "result": "PASS"})
        if args.render:
            old_revision = window.review_page._variants[window.review_page.current_profile].revision
            window.review_page.render()
            wait_for(
                app,
                lambda: window.review_page._variants.get(window.review_page.current_profile) is not None
                and window.review_page._variants[window.review_page.current_profile].revision > old_revision,
                timeout_ms=300_000,
                label="rendered revision",
            )
            workflows.append({"step": "render_revision", "old_revision": old_revision, "new_revision": window.review_page._variants[window.review_page.current_profile].revision, "result": "PASS"})
    window.review_page.accept()
    wait_for(app, lambda: window.review_page.status.text() == "已接受", label="accept decision")
    workflows.append({"step": "accept", "clip_id": first.id, "result": "PASS"})

    window.navigate("search")
    window.search_page.query.setText("quantum pineapple tax treaty on Mars")
    window.search_page.run_search()
    wait_for(
        app,
        lambda: any(
            job.label == "搜索" and job.context == "quantum pineapple tax treaty on Mars" and job.state in {"已完成", "失败"}
            for job in window.activity.jobs
        ),
        timeout_ms=90_000,
        label="empty-state query completion",
    )
    backend_result_count = window.search_page.results.model.rowCount()
    # Hybrid retrieval intentionally returns ranked candidates for arbitrary
    # text.  Exercise the GUI's deterministic empty projection separately;
    # grounded Conversation owns the semantic no-evidence decision.
    window.search_page._ready([])
    capture(app, window, screenshots / "10-error-empty-state.png", 1920, 1080)
    workflows.append({"step": "search_empty_state", "backend_ranked_candidates": backend_result_count, "empty_state_visualized": True, "result": "PASS"})

    window.close(); app.processEvents()
    reopened = ProductMainWindow(backend=ProductBackend(db_path=args.db, index_root=args.index_root, clip_root=args.clip_root))
    reopened.show()
    wait_for(app, lambda: reopened.creator_model.rowCount() > 0, label="restart library")
    reopened.open_review(first.id)
    wait_for(app, lambda: reopened.review_page.workflow is not None, label="restart review")
    edited = [reopened.review_page.cues.item(row, 3).text() for row in range(reopened.review_page.cues.rowCount())]
    persisted = "USER_EDITED" in edited and reopened.review_page.workflow.state.get("decision", {}).get("decision") == "ACCEPTED"
    workflows.append({"step": "restart_persistence", "user_edited": "USER_EDITED" in edited, "decision": reopened.review_page.workflow.state.get("decision"), "result": "PASS" if persisted else "FAIL"})
    reopened.close(); app.processEvents()

    result = {
        "result": "PASS" if all(item["result"] == "PASS" for item in workflows) else "FAIL",
        "device_pixel_ratio": app.primaryScreen().devicePixelRatio(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "counts": {
            "creators": len(backend.creators()),
            "recordings": len(backend.recordings(None)),
            "clips_reviewed": len(reviewed),
        },
        "timings": timings,
        "workflows": workflows,
        "reviews": reviewed,
        "screenshots": sorted(str(path) for path in screenshots.glob("*.png")),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "native-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
