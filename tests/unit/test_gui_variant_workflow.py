from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from acfv.clips import ClipVariantService, GuiVariantWorkflowService


class FakeTranslator:
    name = "fake"
    model = "fake-v1"

    def translate(self, text, *, target_language, **_kwargs):
        return f"中译 {text}" if target_language == "zh" else f"English {text}"


def _event_plan(tmp_path: Path) -> Path:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    units = [
        (100_000, 120_000, "early setup.", ["setup"]),
        (120_000, 135_000, "fear setup.", ["setup"]),
        (135_000, 155_000, "event payoff!", ["event", "payoff"]),
        (155_000, 180_000, "reaction.", ["reaction"]),
        (180_000, 220_000, "discussion.", ["aftermath"]),
        (220_000, 245_000, "natural ending.", ["aftermath"]),
    ]
    words = []
    for index, (start, end, text, _roles) in enumerate(units):
        words.append({
            "word_id": f"w{index}", "word": text, "start_ms": start,
            "end_ms": min(end, start + 2_000), "language": "en", "probability": .9,
        })
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({
        "schema_version": "1.0", "recording_id": "recording-1", "event_id": "event-1",
        "clip_id": "clip-1", "source_path": str(source), "source_duration_ms": 400_000,
        "payoff_anchor_ms": 145_000, "source_language": "en", "glossary": {},
        "units": [{"start_ms": start, "end_ms": end, "text": text, "roles": roles}
                  for start, end, text, roles in units],
        "words": words,
    }), encoding="utf-8")
    return path


def _workflow(tmp_path: Path):
    calls = []

    def renderer(**kwargs):
        calls.append(kwargs)
        output = Path(kwargs["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(("subtitle:" + str(kwargs.get("subtitle_path"))).encode("utf-8")
                           if kwargs.get("subtitle_path") else b"clean")
        return {"output_path": str(output)}

    variants = ClipVariantService(renderer=renderer)

    def previews(_video, _duration, target):
        paths = tuple(target / f"subtitle_preview_{name}.jpg" for name in ("start", "middle", "end"))
        for path in paths:
            path.write_bytes(b"jpg")
        return paths

    variants._preview_frames = previews
    workflow = GuiVariantWorkflowService(
        _event_plan(tmp_path), tmp_path / "outputs", variant_service=variants,
        provider=FakeTranslator(), media_validator=lambda path: {"path": str(path), "decode": "PASS"},
    )
    return workflow, calls


def test_generate_all_uses_canonical_service_and_persists_selection(tmp_path: Path) -> None:
    workflow, calls = _workflow(tmp_path)
    progress = []
    results = workflow.generate_all(progress=lambda profile, stage: progress.append((profile, stage)))

    assert len(results) == 4
    assert [row["status"] for row in workflow.variant_rows()[:4]] == ["READY"] * 4
    assert workflow.selected_profile == "STANDARD"
    assert len(calls) == 8
    assert ("SHORT", "BUILDING_BOUNDARY") in progress
    assert ("FULL_EVENT", "VALIDATING") in progress
    workflow.state["variants"]["LONG"]["duration_ms"] = 84_420
    workflow.state["variants"]["FULL_EVENT"]["duration_ms"] = 87_360
    assert workflow.similarity_warning() == "These variants are nearly identical for this event."
    restored = GuiVariantWorkflowService(
        workflow.event_plan_path, workflow.output_root, variant_service=workflow.variant_service,
        provider=FakeTranslator(), media_validator=lambda path: {"path": str(path)},
    )
    assert restored.selected_profile == "STANDARD"
    assert restored.selected_output().is_file()


def test_cue_edits_survive_restart_and_rerender_creates_revision(tmp_path: Path) -> None:
    workflow, _calls = _workflow(tmp_path)
    workflow.generate_all()
    track = workflow.load_track("STANDARD")
    cue = track.cues[0]
    warnings = workflow.save_cues("STANDARD", [{
        "cue_id": item.cue_id,
        "zh_text": "用户编辑中文" if item.cue_id == cue.cue_id else item.zh_text,
        "en_text": "User edited English" if item.cue_id == cue.cue_id else item.en_text,
    } for item in track.cues])
    assert isinstance(warnings, list)

    restored = GuiVariantWorkflowService(
        workflow.event_plan_path, workflow.output_root, variant_service=workflow.variant_service,
        provider=FakeTranslator(), media_validator=lambda path: {"path": str(path), "decode": "PASS"},
    )
    edited = restored.load_track("STANDARD")
    assert edited.cues[0].zh_text == "用户编辑中文"
    receipt = restored.rerender("STANDARD")
    assert receipt["revision"] == 1
    assert receipt["changed_cues"] == 1
    assert Path(receipt["output_path"]).is_file()
    assert receipt["old_hash"] != receipt["new_hash"]
    assert "revision_001" in receipt["output_path"]

    restored.select_variant("STANDARD")
    decision = restored.record_decision("ACCEPTED")
    assert decision["profile"] == "STANDARD"
    again = GuiVariantWorkflowService(
        workflow.event_plan_path, workflow.output_root, variant_service=workflow.variant_service,
        provider=FakeTranslator(), media_validator=lambda path: {"path": str(path)},
    )
    assert again.state["decision"]["decision"] == "ACCEPTED"
    assert again.state["variants"]["STANDARD"]["revision"] == 1


def test_one_variant_failure_does_not_abort_generate_all(tmp_path: Path, monkeypatch) -> None:
    workflow, _calls = _workflow(tmp_path)
    original = workflow.variant_service.generate_one

    def fail_long(plan, request, **kwargs):
        if request.profile.value == "LONG":
            raise RuntimeError("render boom")
        return original(plan, request, **kwargs)

    monkeypatch.setattr(workflow.variant_service, "generate_one", fail_long)
    results = workflow.generate_all()
    assert len(results) == 3
    statuses = {row["profile"]: row["status"] for row in workflow.variant_rows()}
    assert statuses["LONG"] == "FAILED"
    assert statuses["SHORT"] == statuses["STANDARD"] == statuses["FULL_EVENT"] == "READY"


def test_empty_bilingual_edit_is_blocked(tmp_path: Path) -> None:
    workflow, _calls = _workflow(tmp_path)
    workflow.generate_selected("STANDARD")
    track = workflow.load_track("STANDARD")
    with pytest.raises(ValueError, match="both Chinese and English"):
        workflow.save_cues("STANDARD", [{
            "cue_id": cue.cue_id, "zh_text": "", "en_text": cue.en_text,
        } for cue in track.cues])


def test_review_widget_loads_deep_link_variants_and_cues(tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip("PyQt5.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    workflow, _calls = _workflow(tmp_path)
    workflow.generate_all()

    from PyQt5.QtWidgets import QApplication
    from acfv.ui.tabs.review_tab import ReviewTab

    app = QApplication.instance() or QApplication([])
    widget = ReviewTab(config_manager=object())
    widget.open_event_plan(workflow.event_plan_path, recording_id="recording-1", output_root=workflow.output_root)
    assert widget.duration_profile.currentData() == "STANDARD"
    assert widget.variant_table.item(0, 9).text() == "READY"
    assert widget.variant_table.item(3, 9).text() == "READY"
    assert widget.cue_table.rowCount() > 0
    assert widget._media_path and widget._media_path.name == "clip_bilingual.mp4"
    assert "recording-1" in widget.event_header.text()
    widget.close()
    app.processEvents()


def test_moved_workflow_rebases_owned_paths_even_when_original_still_exists(tmp_path: Path) -> None:
    original = tmp_path / "original"
    original.mkdir()
    workflow, _calls = _workflow(original)
    workflow.generate_selected("STANDARD")
    relocated_root = tmp_path / "relocated" / "clips"
    shutil.copytree(workflow.output_root, relocated_root)

    reopened = GuiVariantWorkflowService(
        workflow.event_plan_path,
        relocated_root,
        variant_service=workflow.variant_service,
        provider=FakeTranslator(),
        media_validator=lambda path: {"valid": path.is_file()},
    )

    row = next(item for item in reopened.variant_rows() if item["profile"] == "STANDARD")
    assert Path(reopened.state["output_root"]) == relocated_root.resolve()
    assert Path(row["base_output_path"]).is_relative_to(relocated_root.resolve())
    assert Path(row["latest_output_path"]).is_relative_to(relocated_root.resolve())


def test_proposed_clip_can_be_rejected_without_rendering(tmp_path: Path) -> None:
    workflow, _calls = _workflow(tmp_path)
    decision = workflow.record_decision("REJECTED", reason="Wrong content")

    assert decision["decision"] == "REJECTED"
    assert decision["output_path"] is None
    assert workflow.state["decision"]["reason"] == "Wrong content"
