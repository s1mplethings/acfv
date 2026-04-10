from pathlib import Path
import yaml
import pytest
from types import SimpleNamespace
from acfv.backend import service as backend_service
from acfv.backend.job_manager import JobManager
from acfv.cli import pipeline as cli_pipeline
from acfv.pipeline.stages import get_stage_plan, normalize_stage_name


def test_docs_and_specs_exist():
    required = [
        "docs/00_overview.md",
        "docs/01_architecture.md",
        "docs/02_workflow.md",
        "docs/03_quality_gates.md",
        "specs/index.md",
        "specs/modules/transcribe_audio/spec.md",
        "specs/modules/unified_pipeline/spec.md",
    ]
    for item in required:
        assert Path(item).exists(), f"missing required doc/spec: {item}"


def test_keywords_yaml_has_core_keys():
    data = yaml.safe_load(Path("ai_context/keywords.yaml").read_text(encoding="utf-8"))
    for key in ["entrypoints", "invariants", "error_signatures", "hotspots", "tags"]:
        assert key in data, f"keywords.yaml missing {key}"
    assert "verify" in data["entrypoints"], "verify entrypoint must be defined"


def test_backend_service_job_lifecycle(monkeypatch, tmp_path):
    def _fake_runner(*, input_source, chat_path, config_manager, run_dir, output_clips_dir, progress_callback=None, metadata=None):
        if progress_callback:
            progress_callback("ingest_video", 1, 1, "done")
            progress_callback("extract_audio", 1, 1, "done")
            progress_callback("build_audio_chunk_manifest", 1, 1, "done")
            progress_callback("transcribe_chunks", 1, 1, "done")
            progress_callback("merge_transcript", 1, 1, "done")
            progress_callback("optional_analysis", 1, 1, "done")
            progress_callback("select_segments", 1, 1, "done")
            progress_callback("build_clip_manifest", 1, 1, "done")
            progress_callback("render_clips_batch", 1, 1, "done")
            progress_callback("export_results", 1, 1, "done")
        run_dir = Path(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        clip_path = Path(output_clips_dir) / "clip_001.mp4"
        clip_path.write_text("ok", encoding="utf-8")
        return {
            "clips": [str(clip_path)],
            "run_dir": str(run_dir),
            "contract_output": {
                "schema_version": "1.0.0",
                "clips": [str(clip_path)],
                "run_dir": str(run_dir),
            },
        }

    monkeypatch.setattr(backend_service, "_manager", JobManager(pipeline_runner=_fake_runner))

    run_dir = tmp_path / "run_001"
    job = backend_service.create_job(
        video_path=str(tmp_path / "video.mp4"),
        run_dir=run_dir,
        output_clips_dir=str(run_dir),
        metadata={"source": "test"},
    )
    status = backend_service.wait_for_job(job["job_id"], timeout=5)

    assert status["status"] == "succeeded"
    assert status["current_stage"] == "completed"
    assert status["result"]["clips"]
    assert backend_service.list_artifacts(job["job_id"])
    assert status["metadata"]["stage_plan"] == get_stage_plan()
    assert any("[progress]" in line for line in backend_service.get_logs(job["job_id"]))


def test_backend_service_failure_state(monkeypatch, tmp_path):
    def _failing_runner(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(backend_service, "_manager", JobManager(pipeline_runner=_failing_runner))

    job = backend_service.create_job(
        video_path=str(tmp_path / "video.mp4"),
        run_dir=tmp_path / "run_002",
        output_clips_dir=str(tmp_path / "run_002"),
    )
    status = backend_service.wait_for_job(job["job_id"], timeout=5)

    assert status["status"] == "failed"
    assert status["error_summary"] == "boom"


def test_cli_pipeline_uses_backend_service(monkeypatch, tmp_path):
    called = {}

    monkeypatch.setattr(cli_pipeline, "setup_logging", lambda settings: None)
    monkeypatch.setattr(cli_pipeline.Settings, "from_yaml", staticmethod(lambda path: SimpleNamespace(workdir=str(tmp_path))))

    def _fake_create_job(**kwargs):
        called["create_job"] = kwargs
        return {"job_id": "run_cli_001"}

    def _fake_wait_for_job(job_id, timeout=None):
        called["wait_for_job"] = job_id
        return {"status": "succeeded", "result": {"clips": ["clip_001.mp4"]}}

    monkeypatch.setattr(cli_pipeline.backend_service, "create_job", _fake_create_job)
    monkeypatch.setattr(cli_pipeline.backend_service, "wait_for_job", _fake_wait_for_job)

    cli_pipeline.clip(url="demo", out_dir=str(tmp_path / "runs"), cfg=str(tmp_path / "config.yaml"))

    assert called["create_job"]["metadata"]["entrypoint"] == "acfv.cli.pipeline.clip"
    assert called["create_job"]["metadata"]["ingest_workdir"] == str(tmp_path)
    assert called["create_job"]["video_path"] == "demo"
    assert called["wait_for_job"] == "run_cli_001"


def test_legacy_pipeline_backend_forwards_to_service(monkeypatch, tmp_path):
    from acfv.features.modules import pipeline_backend as legacy_backend

    called = {}

    def _fake_create_job(**kwargs):
        called["create_job"] = kwargs
        return {"job_id": "legacy_001"}

    def _fake_wait_for_job(job_id, timeout=None):
        called["wait_for_job"] = job_id
        return {"status": "succeeded", "result": {"clips": ["clip_legacy.mp4"]}}

    monkeypatch.setattr(backend_service, "create_job", _fake_create_job)
    monkeypatch.setattr(backend_service, "wait_for_job", _fake_wait_for_job)

    output_dir, clips, has_chat = legacy_backend.run_pipeline(
        cfg_manager=SimpleNamespace(get=lambda *args, **kwargs: None),
        video=str(tmp_path / "video.mp4"),
        chat=str(tmp_path / "chat.html"),
        has_chat=True,
        chat_output="",
        transcription_output="",
        video_emotion_output="",
        analysis_output="",
        output_clips_dir=str(tmp_path / "run_legacy"),
        video_clips_dir=str(tmp_path / "video_root"),
        progress_callback=None,
    )

    assert called["create_job"]["metadata"]["entrypoint"] == "features.modules.pipeline_backend.run_pipeline"
    assert called["wait_for_job"] == "legacy_001"
    assert clips == ["clip_legacy.mp4"]
    assert has_chat is True
    assert output_dir == str(tmp_path / "run_legacy")


def test_stage_plan_order_and_mapping():
    stage_names = [stage["name"] for stage in get_stage_plan()]
    assert stage_names == [
        "ingest_video",
        "extract_audio",
        "build_audio_chunk_manifest",
        "transcribe_chunks",
        "merge_transcript",
        "optional_analysis",
        "select_segments",
        "build_clip_manifest",
        "render_clips_batch",
        "export_results",
    ]
    assert normalize_stage_name("audio_extract") == "extract_audio"
    assert normalize_stage_name("video_emotion") == "optional_analysis"
    assert normalize_stage_name("clip") == "render_clips_batch"


def test_cli_dry_run_plan_uses_shared_stage_source(capsys):
    with pytest.raises((SystemExit, cli_pipeline.typer.Exit)):
        cli_pipeline.clip(url="demo", out_dir="runs/out", cfg=None, dry_run_plan=True)
    captured = capsys.readouterr().out
    assert "ingest_video" in captured
    assert "render_clips_batch" in captured
