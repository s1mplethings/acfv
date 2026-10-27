import json
from pathlib import Path

import numpy as np

from acfv.library import LibraryService, RecordingStatus
from acfv.live import LiveProcessingService, SegmentStatus
from acfv.moments import MomentStatus
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex, SearchScope


def _encoder(texts):
    values = []
    for text in texts:
        lowered = text.casefold()
        values.append(np.asarray([lowered.count("overwatch") + 0.01, lowered.count("segment") + 0.01], dtype=np.float32))
    return np.stack(values)


def _setup(tmp_path: Path):
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    source = library.add_source(creator.id, platform="twitch", external_id="alice", channel_name="Alice")
    recording = library.register_recording(
        creator_id=creator.id,
        source_id=source.id,
        title="Alice live",
        recording_status=RecordingStatus.RECORDING,
        require_file=False,
    )
    calls = []

    def transcriber(path: Path, _output: Path):
        calls.append(path.name)
        number = int(path.stem.rsplit("_", 1)[-1])
        text = "Overwatch clutch" if number == 3 else f"segment {number}"
        return {"segments": [{"start": 1.0, "end": 4.0, "text": text, "confidence": 0.9}]}

    index = PersistentMomentIndex(library.repository, tmp_path / "index", encoder=_encoder)
    live = LiveProcessingService(recording.id, library.repository, root=tmp_path / "recording", transcriber=transcriber, moment_index=index)
    return library, recording, live, calls, index


def test_five_closed_segments_are_continuous_processed_once_and_live_searchable(tmp_path: Path) -> None:
    library, recording, live, calls, index = _setup(tmp_path)
    live.append_chat(123_000, "viewer", "Overwatch wow")
    for number in range(1, 6):
        path = tmp_path / f"segment_{number:06d}.ts"
        path.write_bytes(b"media")
        live.close_segment(path.stem, path, (number - 1) * 60_000, number * 60_000)

    manifest = json.loads(live.manifest_path.read_text(encoding="utf-8"))
    assert [item["status"] for item in manifest["segments"]] == [SegmentStatus.DONE.value] * 5
    assert [item["start_ms"] for item in manifest["segments"]] == [0, 60_000, 120_000, 180_000, 240_000]
    assert [item["end_ms"] for item in manifest["segments"]] == [60_000, 120_000, 180_000, 240_000, 300_000]
    assert calls == [f"segment_{number:06d}.ts" for number in range(1, 6)]

    live.close_segment("segment_000003", tmp_path / "segment_000003.ts", 120_000, 180_000)
    assert calls.count("segment_000003.ts") == 1
    merged = json.loads(live.merged_path.read_text(encoding="utf-8"))
    assert merged["segments"][2]["start"] == 121.0
    assert "Overwatch wow" in library.repository.list_moments(recording_id=recording.id)[2].chat_text

    retrieval = HybridRetrievalService(library.repository, index, reranker=lambda _q, texts: [float("overwatch" in text.casefold()) for text in texts])
    hits = retrieval.search("Overwatch", scope=SearchScope.LIVE_SESSION, recording_id=recording.id)
    assert hits and hits[0].moment_status == MomentStatus.PROVISIONAL.value

    events = [json.loads(line) for line in live.events_path.read_text(encoding="utf-8").splitlines()]
    assert len([event for event in events if event["type"] == "segment_closed"]) == 5


def test_failed_segment_is_retryable_and_finalization_replaces_provisional_index(tmp_path: Path) -> None:
    library, recording, live, calls, index = _setup(tmp_path)
    path = tmp_path / "segment_000001.ts"
    path.write_bytes(b"media")
    original = live.transcriber
    live.transcriber = lambda *_args: (_ for _ in ()).throw(RuntimeError("temporary ASR failure"))
    try:
        live.close_segment(path.stem, path, 0, 60_000)
    except RuntimeError:
        pass
    assert json.loads(live.manifest_path.read_text(encoding="utf-8"))["segments"][0]["status"] == SegmentStatus.FAILED.value

    live.transcriber = original
    assert live.retry_failed() == 1
    final = live.finalize(final_source=path)
    assert final and all(moment.status == MomentStatus.FINAL for moment in final)
    assert library.get_recording(recording.id).recording_status == RecordingStatus.COMPLETE
    assert all(row.status == MomentStatus.FINAL.value for row in index.rows())

    repeated = live.finalize(final_source=path)
    assert [moment.id for moment in repeated] == [moment.id for moment in final]
    assert len(index.rows()) == len(final)


def test_default_live_transcriber_uses_canonical_transcriber(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("KMP_DUPLICATE_LIB_OK", "TRUE")
    from acfv.steps.transcribe_audio import impl

    captured = {}

    def transcribe(payload):
        captured.update(payload)
        return {"segments": []}

    monkeypatch.setattr(impl, "transcribe_audio", transcribe)
    source = tmp_path / "segment.ts"
    output = tmp_path / "work" / "transcript.json"

    assert LiveProcessingService._default_transcriber(source, output) == {"segments": []}
    assert captured["source_path"] == str(source)
    assert captured["transcript_path"] == str(output)


def test_live_warmup_discovers_transcribe_runtime_without_loading_media(monkeypatch, tmp_path: Path) -> None:
    library, _recording, live, _calls, _index = _setup(tmp_path)
    monkeypatch.setenv("KMP_DUPLICATE_LIB_OK", "TRUE")
    from acfv.steps.transcribe_audio import impl

    calls = []
    monkeypatch.setattr(impl, "_resolve_transcribe_python", lambda: calls.append("resolve") or "python")

    assert live.warmup() is True
    assert calls == ["resolve"]
    assert library.list_recordings()


def test_transcript_entries_are_bounded_to_closed_segment_timeline(tmp_path: Path) -> None:
    library, recording, live, _calls, _index = _setup(tmp_path)
    payloads = iter(
        [
            {"segments": [{"start": 59.0, "end": 62.0, "text": "first tail"}]},
            {"segments": [{"start": 0.0, "end": 3.0, "text": "second head"}]},
        ]
    )
    live.transcriber = lambda *_args: next(payloads)
    for number in range(2):
        path = tmp_path / f"boundary_{number:06d}.ts"
        path.write_bytes(b"media")
        live.close_segment(path.stem, path, number * 60_000, (number + 1) * 60_000)

    merged = json.loads(live.merged_path.read_text(encoding="utf-8"))["segments"]
    assert [(item["start"], item["end"]) for item in merged] == [(59.0, 60.0), (60.0, 63.0)]
    assert all(merged[index]["start"] >= merged[index - 1]["end"] for index in range(1, len(merged)))
    assert library.get_recording(recording.id) is not None
