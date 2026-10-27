from __future__ import annotations

import os
from pathlib import Path
import threading

import pytest


pytest.importorskip("PyQt5.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from acfv.product_gui.backend import ProductBackend
from acfv.product_gui.controllers import ActivityController
from acfv.product_gui.models import CreatorModel, MomentModel, RecordingModel
from acfv.product_gui.player import MediaPlayer
from acfv.product_gui.theme import TOKENS, stylesheet
from acfv.product_gui.viewmodels import CreatorVM, MomentVM, RecordingVM
from acfv.product_gui.workers import GuiExecutor


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_design_system_is_centralized_and_accessible() -> None:
    qss = stylesheet()
    assert TOKENS.accent in qss
    assert "Segoe UI" in qss
    assert "QPushButton:disabled" in qss
    assert "QToolTip" in qss


def test_model_view_scales_without_creating_widgets(app) -> None:
    recordings = [
        RecordingVM(str(index), "creator", f"Recording {index}", "local", "2026-10-12", 60_000, "en", "可用", "", False)
        for index in range(100)
    ]
    moments = [
        MomentVM(str(index), "creator", "recording", "Recording", index * 1000, index * 1000 + 5000, f"Moment {index}", "excerpt")
        for index in range(1000)
    ]
    recording_model = RecordingModel(recordings)
    moment_model = MomentModel(moments)
    assert recording_model.rowCount() == 100
    assert moment_model.rowCount() == 1000
    assert not any(hasattr(row, "show") for row in recording_model.rows + moment_model.rows)


def test_executor_discards_stale_results(app) -> None:
    executor = GuiExecutor(max_workers=1)
    delivered = []
    executor.result_ready.connect(lambda token, value: delivered.append((token, value)))
    old = executor.invalidate("search.query")
    current = executor.invalidate("search.query")
    executor._deliver_result(old, ["old"])
    executor._deliver_result(current, ["current"])
    assert delivered == [(current, ["current"])]
    executor.shutdown()


def test_executor_drops_inflight_completion_after_shutdown(app) -> None:
    executor = GuiExecutor(max_workers=1)
    gate = threading.Event()
    delivered = []
    executor.result_ready.connect(lambda token, value: delivered.append((token, value)))
    executor.submit("thumbnail", lambda: gate.wait(2) or "done")
    executor.shutdown(wait=False)
    gate.set()
    for _ in range(10):
        app.processEvents()
    assert delivered == []


def test_backend_adapter_projects_canonical_library(tmp_path: Path) -> None:
    backend = ProductBackend(
        db_path=tmp_path / "library.db",
        index_root=tmp_path / "index",
        clip_root=tmp_path / "clips",
    )
    creator = backend.library.create_creator("Test Creator")
    media = tmp_path / "sample.mp4"
    media.write_bytes(b"not-real-media")
    recording = backend.library.register_recording(
        creator_id=creator.id,
        title="Real title",
        local_path=media,
        require_file=False,
    )
    creators = backend.creators()
    rows = backend.recordings(creator.id)
    assert creators[0].name == "Test Creator"
    assert creators[0].recording_count == 1
    assert rows[0].id == recording.id
    assert rows[0].title == "Real title"
    assert rows[0].missing_media is False


def test_relink_updates_canonical_recording_path(tmp_path: Path) -> None:
    backend = ProductBackend(db_path=tmp_path / "library.db", index_root=tmp_path / "index", clip_root=tmp_path / "clips")
    creator = backend.library.create_creator("Creator")
    recording = backend.library.register_recording(creator_id=creator.id, title="Missing", require_file=False)
    media = tmp_path / "replacement.mp4"
    media.write_bytes(b"replacement")

    row = backend.relink_recording(recording.id, str(media))

    assert row.media_path == str(media.resolve())
    assert row.missing_media is False


def test_activity_distinguishes_backend_jobs_from_ephemeral_gui_tasks(app) -> None:
    activity = ActivityController()
    gui_job = activity.begin("Search", "query")
    activity.track_backend("run_20261012_132724", "Processing", "video.mp4")

    assert gui_job not in activity._backend_job_ids
    assert "run_20261012_132724" in activity._backend_job_ids
    activity.update_backend(
        "run_20261012_132724",
        {"job": {"status": "succeeded"}, "overall_progress": {"percent": 100}},
    )
    assert "run_20261012_132724" not in activity._backend_job_ids


def test_player_exposes_external_fallback_for_codec_error(app, tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"not-a-real-video")
    player = MediaPlayer()
    player._path = str(media)
    player._show_media_error("codec unavailable")

    assert player.error_label.isVisible() is False  # parent is not shown
    assert player.error_label.text() == "播放器不可用：codec unavailable"
    assert player.external_button.isHidden() is False


def test_product_gui_has_no_second_domain_or_thread_implementation() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "acfv" / "product_gui"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
    assert "class GuiLibraryDB" not in source
    assert "class GuiSearchEngine" not in source
    assert "class GuiTranslationEngine" not in source
    assert "QThread" not in source
    assert "threading.Thread" not in source
    assert "asyncio" not in source

