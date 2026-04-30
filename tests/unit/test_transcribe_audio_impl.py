from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from acfv.steps.transcribe_audio import impl


def test_check_ffmpeg_availability_uses_cache(monkeypatch):
    calls = {"count": 0}

    def fake_run(*args, **kwargs):
        calls["count"] += 1
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(impl.subprocess, "run", fake_run)
    impl._FFMPEG_AVAILABLE_CACHE = None
    assert impl.check_ffmpeg_availability() is True
    assert impl.check_ffmpeg_availability() is True
    assert calls["count"] == 1
    impl._FFMPEG_AVAILABLE_CACHE = None


def test_diagnostics_checkpoint_throttles_non_critical_events(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ACFV_TRANSCRIBE_CHECKPOINT_INTERVAL_SEC", "999")
    diag = impl._TranscribeDiagnostics(tmp_path, enabled=True)
    diag.event("heartbeat", value=1)
    diag.event("heartbeat", value=2)

    checkpoint = tmp_path / "transcribe_checkpoint.json"
    assert checkpoint.exists()
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert payload["stage"] == "heartbeat"
    assert payload["value"] == 1


def test_diagnostics_checkpoint_writes_chunk_start_immediately(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ACFV_TRANSCRIBE_CHECKPOINT_INTERVAL_SEC", "999")
    diag = impl._TranscribeDiagnostics(tmp_path, enabled=True)
    diag.event("heartbeat", value=1)
    diag.event("chunk_transcribe_start", chunk_index=39)

    checkpoint = tmp_path / "transcribe_checkpoint.json"
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert payload["stage"] == "chunk_transcribe_start"
    assert payload["chunk_index"] == 39


def test_process_audio_segments_fallback_path(monkeypatch, tmp_path: Path):
    calls = {"count": 0}

    def fake_run(payload, work_dir, progress_callback=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("primary failed")
        return {"segments": [{"start": 0.0, "end": 1.0, "text": "ok", "speaker": "unk", "confidence": 0.5}]}

    monkeypatch.setattr(impl, "_guard_enabled", lambda: True)
    monkeypatch.setattr(impl, "_fallback_enabled", lambda: True)
    monkeypatch.setattr(impl, "_run_transcribe_subprocess", fake_run)

    output = tmp_path / "transcript.json"
    segments = impl.process_audio_segments(
        audio_path="dummy.mp4",
        output_file=str(output),
        segment_length=60,
    )
    assert len(segments) == 1
    assert calls["count"] == 2


def test_run_transcribe_subprocess_guarded_retries_with_cpu_faster_whisper(monkeypatch, tmp_path: Path):
    calls = {"count": 0}
    payloads: list[dict] = []

    def fake_run(payload, work_dir, progress_callback=None, checkpoint_callback=None):
        payloads.append(dict(payload))
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("Could not locate cudnn_ops_infer64_8.dll")
        return {"segments": [{"start": 0.0, "end": 1.0, "text": "ok"}], "engine": payload["engine"], "language": "en"}

    monkeypatch.setattr(impl, "_run_transcribe_subprocess", fake_run)
    monkeypatch.setattr(impl, "_fallback_enabled", lambda: True)
    monkeypatch.setattr(impl, "FASTER_WHISPER_AVAILABLE", True)

    result = impl.run_transcribe_subprocess_guarded(
        {"engine": "faster-whisper", "device": "cuda", "model_size": "large-v3-turbo"},
        tmp_path,
    )

    assert calls["count"] == 2
    assert result["engine"] == "faster-whisper"
    assert payloads[1]["device"] == "cpu"
    assert payloads[1]["model_size"] == "medium"


def test_build_fallback_payload_uses_openai_whisper_cpu_when_faster_whisper_missing(monkeypatch):
    monkeypatch.setattr(impl, "FASTER_WHISPER_AVAILABLE", False)

    payload = impl._build_fallback_payload(
        {"engine": "faster-whisper", "device": "cuda", "model_size": "medium"}
    )

    assert payload["engine"] == "openai-whisper"
    assert payload["device"] == "cpu"
    assert payload["model_size"] == "small"


def test_resolve_transcribe_python_prefers_better_env(monkeypatch):
    monkeypatch.setattr(impl, "_TRANSCRIBE_PYTHON_CACHE", None)
    monkeypatch.setattr(impl.sys, "executable", r"D:\anaconda\python.exe")
    monkeypatch.setattr(impl, "TORCH_AVAILABLE", True)
    monkeypatch.setattr(impl, "FASTER_WHISPER_AVAILABLE", False)
    monkeypatch.setattr(
        impl,
        "torch",
        SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)),
        raising=False,
    )
    monkeypatch.setattr(
        impl,
        "_candidate_python_paths",
        lambda current_python: [Path(r"D:\anaconda\envs\clip\python.exe")],
    )
    monkeypatch.setattr(
        impl,
        "_probe_python_for_transcribe",
        lambda path: {"torch": True, "faster_whisper": True, "cuda": True},
    )

    resolved = impl._resolve_transcribe_python()
    assert resolved == r"D:\anaconda\envs\clip\python.exe"


def test_build_transcribe_subprocess_env_prepends_src_root(monkeypatch):
    monkeypatch.setattr(impl, "_src_root", lambda: Path(r"E:\Cliper\acfv\src"))
    monkeypatch.setenv("PYTHONPATH", r"C:\existing")
    monkeypatch.delenv("KMP_DUPLICATE_LIB_OK", raising=False)

    env = impl._build_transcribe_subprocess_env()

    assert env["PYTHONPATH"] == r"E:\Cliper\acfv\src" + impl.os.pathsep + r"C:\existing"
    assert env["KMP_DUPLICATE_LIB_OK"] == "TRUE"


def test_build_transcribe_subprocess_env_prepends_selected_env_dll_paths(monkeypatch):
    monkeypatch.setattr(impl, "_src_root", lambda: Path(r"E:\Cliper\acfv\src"))
    monkeypatch.setattr(
        impl,
        "_transcribe_runtime_path_entries",
        lambda python_executable=None: [
            r"D:\anaconda\envs\clip\Library\bin",
            r"D:\anaconda\envs\clip\Lib\site-packages\torch\lib",
        ],
    )
    monkeypatch.setenv("PATH", r"D:\anaconda;C:\Windows")

    env = impl._build_transcribe_subprocess_env(r"D:\anaconda\envs\clip\python.exe")

    path_parts = env["PATH"].split(impl.os.pathsep)
    assert path_parts[:2] == [
        r"D:\anaconda\envs\clip\Library\bin",
        r"D:\anaconda\envs\clip\Lib\site-packages\torch\lib",
    ]


def test_load_transcriber_reuses_cached_model(monkeypatch):
    calls: list[tuple[str, str]] = []
    sentinel = object()

    def fake_load(model_size, device):
        calls.append((model_size, device))
        return sentinel

    impl._clear_transcriber_cache()
    monkeypatch.setattr(impl, "WHISPER_AVAILABLE", True)
    monkeypatch.setattr(impl, "FASTER_WHISPER_AVAILABLE", False)
    monkeypatch.setattr(impl, "TORCH_AVAILABLE", False)
    monkeypatch.setattr(impl, "_load_whisper_model", fake_load)

    first_engine, first_model = impl._load_transcriber("tiny", "cpu", "openai-whisper")
    second_engine, second_model = impl._load_transcriber("tiny", "cpu", "openai-whisper")

    assert first_engine == second_engine == "openai-whisper"
    assert first_model is second_model is sentinel
    assert calls == [("tiny", "cpu")]

    impl._clear_transcriber_cache()


def test_load_transcriber_supports_whisperx(monkeypatch):
    sentinel = object()

    impl._clear_transcriber_cache()
    monkeypatch.setattr(impl, "WHISPERX_AVAILABLE", True)
    monkeypatch.setattr(impl, "_load_whisperx_model", lambda model_size, device: sentinel)

    engine, model = impl._load_transcriber("medium", "cpu", "whisperx")

    assert engine == "whisperx"
    assert model is sentinel
    impl._clear_transcriber_cache()


def test_stabilize_split_duration_caps_large_v3_for_faster_whisper(monkeypatch):
    monkeypatch.setattr(impl, "FASTER_WHISPER_AVAILABLE", True)

    assert impl._stabilize_split_duration("large-v3", "faster-whisper", 120) == 60
    assert impl._stabilize_split_duration("large-v3-turbo", "auto", None) == 60
    assert impl._stabilize_split_duration("medium", "faster-whisper", 120) == 120
    assert impl._stabilize_split_duration("large-v3", "openai-whisper", 120) == 120


def test_run_transcribe_subprocess_guarded_restarts_stalled_payload(monkeypatch, tmp_path: Path):
    calls = {"count": 0}

    def fake_run(payload, work_dir, progress_callback=None, checkpoint_callback=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("transcribe subprocess stalled during chunk 45 for 180s")
        return {"segments": [{"start": 0.0, "end": 1.0, "text": "ok"}], "engine": payload["engine"], "language": "en"}

    monkeypatch.setattr(impl, "_run_transcribe_subprocess", fake_run)
    monkeypatch.setattr(impl, "_fallback_enabled", lambda: True)
    monkeypatch.setenv("ACFV_TRANSCRIBE_STALL_RESTARTS", "1")

    result = impl.run_transcribe_subprocess_guarded(
        {"engine": "faster-whisper", "device": "cuda", "model_size": "medium"},
        tmp_path,
    )

    assert calls["count"] == 2
    assert result["engine"] == "faster-whisper"


def test_run_transcribe_subprocess_guarded_restarts_recycle_request(monkeypatch, tmp_path: Path):
    calls = {"count": 0}

    def fake_run(payload, work_dir, progress_callback=None, checkpoint_callback=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("transcribe subprocess recycle requested after 60 chunks")
        return {"segments": [{"start": 0.0, "end": 1.0, "text": "ok"}], "engine": payload["engine"], "language": "en"}

    monkeypatch.setattr(impl, "_run_transcribe_subprocess", fake_run)

    result = impl.run_transcribe_subprocess_guarded(
        {"engine": "faster-whisper", "device": "cuda", "model_size": "medium"},
        tmp_path,
    )

    assert calls["count"] == 2
    assert result["engine"] == "faster-whisper"


def test_recycle_chunk_limit_defaults_for_faster_whisper():
    assert impl._recycle_chunk_limit("faster-whisper", "cuda") == 60
    assert impl._recycle_chunk_limit("faster-whisper", "cpu") == 60
    assert impl._recycle_chunk_limit("openai-whisper", "cpu") == 0


def test_run_transcribe_subprocess_does_not_repeat_checkpoint_callback_for_stale_checkpoint(
    monkeypatch,
    tmp_path: Path,
):
    checkpoint_payload = {
        "stage": "chunk_transcribe_ok",
        "chunk_index": 38,
        "segments": 30,
        "start_time": 4560.0,
        "end_time": 4680.0,
        "total_duration": 13109.184,
        "result_path": str(tmp_path / "chunk_0038.json"),
    }
    (tmp_path / "transcript.json").write_text(json.dumps({"segments": []}), encoding="utf-8")

    poll_values = iter([None, None, None, 0])
    monotonic_values = iter([0.0, 0.0, 16.0, 16.0])

    class _Proc:
        returncode = 0

        def poll(self):
            return next(poll_values)

        def communicate(self):
            return ("", "")

    callbacks = []
    progresses = []

    monkeypatch.setattr(impl, "_resolve_transcribe_python", lambda: "python")
    monkeypatch.setattr(impl, "_build_transcribe_subprocess_env", lambda python_executable=None: {})
    monkeypatch.setattr(impl.subprocess, "Popen", lambda *args, **kwargs: _Proc())
    monkeypatch.setattr(impl, "_read_checkpoint_payload", lambda path: dict(checkpoint_payload))
    monkeypatch.setattr(impl.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(impl.time, "sleep", lambda _secs: None)

    result = impl._run_transcribe_subprocess(
        {"transcript_path": str(tmp_path / "transcript.json")},
        tmp_path,
        progress_callback=lambda stage, current, total, message: progresses.append((stage, current, total, message)),
        checkpoint_callback=lambda checkpoint: callbacks.append(dict(checkpoint)),
    )

    assert result["segments"] == []
    assert len(callbacks) == 2
    assert len(progresses) == 3


def test_load_faster_whisper_model_prefers_local_cache(monkeypatch):
    calls = []
    sentinel = object()

    monkeypatch.setattr(impl, "FASTER_WHISPER_AVAILABLE", True)
    monkeypatch.setattr(impl, "_ensure_transcribe_runtime_path", lambda: None)
    monkeypatch.setattr(impl, "_resolve_local_faster_whisper_model_path", lambda model_size: "C:/cache/fw-medium")

    def fake_model(source, **kwargs):
        calls.append((source, dict(kwargs)))
        return sentinel

    monkeypatch.setattr(impl, "FasterWhisperModel", fake_model)

    adapter = impl._load_faster_whisper_model("medium", "cpu")

    assert adapter._model is sentinel
    assert calls == [("C:/cache/fw-medium", {"device": "cpu", "compute_type": "int8", "local_files_only": True})]


def test_run_transcribe_subprocess_raises_immediately_on_terminal_checkpoint(monkeypatch, tmp_path: Path):
    checkpoint_payload = {
        "stage": "transcribe_error",
        "error": "unable to access Hugging Face",
        "progress": 50,
    }
    killed = {"value": False}

    class _Proc:
        returncode = None

        def poll(self):
            return None

        def kill(self):
            killed["value"] = True
            self.returncode = -9

        def communicate(self):
            return ("", "")

    monkeypatch.setattr(impl, "_resolve_transcribe_python", lambda: "python")
    monkeypatch.setattr(impl, "_build_transcribe_subprocess_env", lambda python_executable=None: {})
    monkeypatch.setattr(impl.subprocess, "Popen", lambda *args, **kwargs: _Proc())
    monkeypatch.setattr(impl, "_read_checkpoint_payload", lambda path: dict(checkpoint_payload))
    monkeypatch.setattr(impl.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(impl.time, "sleep", lambda _secs: None)

    try:
        impl._run_transcribe_subprocess({"transcript_path": str(tmp_path / "transcript.json")}, tmp_path)
    except RuntimeError as exc:
        assert "unable to access Hugging Face" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert killed["value"] is True


def test_transcribe_with_splitting_reuses_existing_chunk_results(monkeypatch, tmp_path: Path):
    for idx in (0, 1):
        chunk_dir = tmp_path / "chunks" / f"chunk_{idx:04d}"
        chunk_dir.mkdir(parents=True)
        (chunk_dir / "transcript.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "chunk_id": f"chunk_{idx:04d}",
                    "index": idx,
                    "start_sec": float(idx * 60),
                    "end_sec": float((idx + 1) * 60),
                    "language": "en",
                    "segments": [{"start": float(idx * 60), "end": float(idx * 60 + 1), "text": f"cached-{idx}", "speaker": "unk", "confidence": 0.5}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr(impl, "extract_audio_segment_safe", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not extract")))
    monkeypatch.setattr(impl, "_transcribe_file", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not transcribe")))

    segments, language = impl._transcribe_with_splitting(
        whisper_model=object(),
        audio_path=tmp_path / "dummy.wav",
        duration=120.0,
        language="en",
        prompt=None,
        split_duration=60,
        chunk_result_dir=tmp_path / "chunks",
    )

    assert language == "en"
    assert len(segments) == 2
    assert [seg["text"] for seg in segments] == ["cached-0", "cached-1"]


def test_transcribe_with_splitting_cleans_up_after_each_chunk(monkeypatch, tmp_path: Path):
    cleaned: list[tuple[str, str]] = []

    def fake_extract(_audio_path, start_sec, end_sec, chunk_path):
        chunk_path.write_bytes(b"wav")
        return True

    def fake_transcribe(_model, chunk_path, language, prompt, offset):
        return ([{"start": offset, "end": offset + 1.0, "text": chunk_path.stem, "speaker": "unk", "confidence": 0.5}], language)

    monkeypatch.setattr(impl, "extract_audio_segment_safe", fake_extract)
    monkeypatch.setattr(impl, "_transcribe_file", fake_transcribe)
    monkeypatch.setattr(
        impl,
        "_cleanup_after_chunk",
        lambda chunk_path, device_hint=None: cleaned.append((chunk_path.name if chunk_path else "", str(device_hint))),
    )

    segments, language = impl._transcribe_with_splitting(
        whisper_model=SimpleNamespace(device="cuda"),
        audio_path=tmp_path / "dummy.wav",
        duration=120.0,
        language="en",
        prompt=None,
        split_duration=60,
        chunk_result_dir=tmp_path / "chunks",
    )

    assert language == "en"
    assert len(segments) == 2
    assert cleaned == [("chunk_0.wav", "cuda"), ("chunk_1.wav", "cuda")]
