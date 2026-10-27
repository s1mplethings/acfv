from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from acfv.human_review.gui import HumanReviewWindow
from acfv.human_review.models import ReviewSample, ReviewTask
from acfv.human_review.repository import HumanReviewRepository


_APP: QApplication | None = None


def _app() -> QApplication:
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _window(tmp_path: Path) -> HumanReviewWindow:
    _app()
    repo = HumanReviewRepository(tmp_path / "human_review_test.sqlite")
    repo.replace_dataset([
        ReviewSample("asr", ReviewTask.ASR, prompt={"current_asr": "hello"}),
        ReviewSample("trusted", ReviewTask.TRUSTED_SPEECH, prompt={"predicted_creator": "Saruei", "transcript": "hello"}),
        ReviewSample("shadow-pair", ReviewTask.ADAPTIVE_ASR, prompt={"a": "hello", "b": "hullo"}, private={"strategy_a": "GENERIC_PROVIDER", "strategy_b": "CREATOR_ADAPTER"}),
        ReviewSample("translation", ReviewTask.TRANSLATION, prompt={"source": "x", "a": "a", "b": "b"}, private={"pair_id": "tr", "provider_a": "secret-a"}),
        ReviewSample("boundary", ReviewTask.BOUNDARY),
        ReviewSample("watch", ReviewTask.WATCHABILITY, private={"pair_id": "watch", "strategy_a": "secret"}),
        ReviewSample("subtitle", ReviewTask.SUBTITLE, prompt={"mode": "cue", "english": "Hi", "chinese": "嗨"}),
        ReviewSample("publish", ReviewTask.PUBLISHABILITY),
    ], {"dataset_version": "test"})
    return HumanReviewWindow(repo, output_root=tmp_path / "exports")


def test_single_window_has_only_required_primary_navigation(tmp_path: Path) -> None:
    window = _window(tmp_path)
    assert window.windowTitle() == "ACFV · Human Review Lab"
    assert set(window.nav) == {"overview", "asr", "identity", "trusted_speech", "adaptive_asr", "translation", "boundary", "watchability", "subtitle", "publishability", "analysis"}
    assert "dataset" not in window.nav and "settings" not in window.nav and "export" not in window.nav
    window.close()


def test_fast_answer_autosaves_and_analysis_refreshes(tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.open_task(ReviewTask.ASR)
    page = window.review_pages[ReviewTask.ASR]
    assert page.current and page.current.sample_id == "asr"
    page.choice_buttons[0].click()
    page.save()
    saved = window.repository.annotation("asr")
    assert saved and saved["answer"]["choice"] == "correct"
    assert window._analysis_dirty
    window.show_page("analysis")
    assert not window._analysis_dirty
    assert window.analysis_page.raw.toPlainText()
    window.close()


def test_trusted_speech_requires_and_persists_both_independent_checks(tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.settings["auto_next"] = False
    window.open_task(ReviewTask.TRUSTED_SPEECH)
    page = window.review_pages[ReviewTask.TRUSTED_SPEECH]
    assert page.current and page.current.sample_id == "trusted"
    page.choice_buttons[0].click()
    page.save()
    assert window.repository.annotation("trusted") is None
    assert "Choose an answer" in page.saved.text()
    page.choice_buttons[2].click()
    page.save()
    saved = window.repository.annotation("trusted")
    assert saved and saved["answer"] == {"speaker": "correct", "transcript": "correct"}
    window.close()


def test_adaptive_asr_pair_remains_blind_until_answer(tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.settings["auto_next"] = False
    window.settings["reveal_after_answer"] = True
    window.open_task(ReviewTask.ADAPTIVE_ASR)
    page = window.review_pages[ReviewTask.ADAPTIVE_ASR]
    assert "GENERIC_PROVIDER" not in page.details_text.text()
    assert "CREATOR_ADAPTER" not in page.details_text.text()
    page.choice_buttons[2].click()
    page.save()
    assert "GENERIC_PROVIDER" in page.details_text.text()
    assert "CREATOR_ADAPTER" in page.details_text.text()
    window.close()


def test_creator_adaptive_tasks_capture_optional_voice_style_change(tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.settings["auto_next"] = False
    window.open_task(ReviewTask.ASR)
    page = window.review_pages[ReviewTask.ASR]
    style = page.more_fields["voice_style_changed"]
    style.setCurrentText("Unsure")
    page.choice_buttons[0].click()
    page.save()
    saved = window.repository.annotation("asr")
    assert saved and saved["answer"]["details"]["voice_style_changed"] == "Unsure"
    window.close()


def test_blind_pages_do_not_render_private_identity(tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.open_task(ReviewTask.TRANSLATION)
    page = window.review_pages[ReviewTask.TRANSLATION]
    assert "secret-a" not in page.context.text()
    assert "secret-a" not in page.details_text.text()
    assert "secret-a" not in page.current.presentation() if page.current else False
    window.open_task(ReviewTask.WATCHABILITY)
    assert "secret" not in window.review_pages[ReviewTask.WATCHABILITY].context.text()
    assert "secret" not in window.review_pages[ReviewTask.WATCHABILITY].details_text.text()
    window.close()


def test_resume_tracks_item_on_screen_and_reveals_only_after_answer(tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.settings["auto_next"] = False
    window.settings["reveal_after_answer"] = True
    window.open_task(ReviewTask.TRANSLATION)
    page = window.review_pages[ReviewTask.TRANSLATION]
    assert window.repository.resume_state() == (ReviewTask.TRANSLATION, "translation")
    assert "secret-a" not in page.details_text.text()
    page.choice_buttons[0].click()
    page.save()
    assert "secret-a" in page.details_text.text()
    window.close()


def test_boundary_io_shortcuts_capture_player_position(tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.open_task(ReviewTask.BOUNDARY)
    page = window.review_pages[ReviewTask.BOUNDARY]
    page.player.player.setPosition(1234)
    page._capture_boundary("manual_start_ms")
    page.player.player.setPosition(5678)
    page._capture_boundary("manual_end_ms")
    assert page._answer()["manual_start_ms"] == 1234
    assert page._answer()["manual_end_ms"] == 5678
    window.close()


def test_primary_controls_fit_compact_window(tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.resize(1280, 720)
    window.show()
    _app().processEvents()
    window.open_task(ReviewTask.BOUNDARY)
    _app().processEvents()
    page = window.review_pages[ReviewTask.BOUNDARY]
    assert page.save_next.isVisible()
    assert page.player.height() >= 220
    assert window.minimumWidth() <= 1280 and window.minimumHeight() <= 720
    window.close()
