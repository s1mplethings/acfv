from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from contextlib import contextmanager

from acfv import config as app_config
from acfv.modular.contracts import ART_SEGMENTS, ART_SEGMENTS_SEMANTIC, ART_TRANSCRIPT
from acfv.modular.store import ArtifactStore
from acfv.modular.types import ArtifactEnvelope, ModuleContext
from acfv.modular.plugins.semantic_merge import spec as semantic_spec


def _ctx(run_dir: Path, transcript_payload, segments_payload):
    store = ArtifactStore(run_dir)
    inputs = {
        ART_TRANSCRIPT: ArtifactEnvelope(
            artifact_id="transcript",
            type=ART_TRANSCRIPT,
            payload=transcript_payload,
        ),
        ART_SEGMENTS: ArtifactEnvelope(
            artifact_id="segments",
            type=ART_SEGMENTS,
            payload=segments_payload,
        ),
    }
    return ModuleContext(inputs=inputs, params={}, store=store, run_id=run_dir.name, progress=None)


@contextmanager
def _with_config(temp_values: dict):
    cm = app_config.config_manager
    original = dict(cm.config)
    cm.config.update(temp_values)
    try:
        yield
    finally:
        cm.config = original


def test_semantic_merge_empty_transcript():
    with TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        ctx = _ctx(run_dir, {"segments": []}, {"segments": [{"start_ms": 0, "end_ms": 10000, "score": 1.2}]})
        result = semantic_spec.run(ctx)
        payload = result[ART_SEGMENTS_SEMANTIC]
        assert payload["segments"], "should pass-through when transcript empty"


def test_semantic_merge_target_window():
    segments = []
    for idx in range(200):
        start = float(idx * 2)
        segments.append({"start": start, "end": start + 2.0, "text": "hello world"})
    transcript = {"segments": segments}
    with TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        ctx = _ctx(run_dir, transcript, {"segments": []})
        with _with_config(
            {
                "SEMANTIC_SEGMENT_MODE": True,
                "SEMANTIC_TARGET_DURATION": 300.0,
                "MIN_CLIP_DURATION": 180.0,
                "MAX_CLIP_DURATION": 600.0,
                "MIN_TARGET_CLIP_DURATION": 180.0,
                "SEMANTIC_SIMILARITY_THRESHOLD": 0.1,
                "SEMANTIC_MAX_TIME_GAP": 2.0,
            }
        ):
            result = semantic_spec.run(ctx)
        payload = result[ART_SEGMENTS_SEMANTIC]
        segments = payload["segments"]
        assert segments, "should produce semantic segments"
        first = segments[0]
        duration = (first["end_ms"] - first["start_ms"]) / 1000.0
        assert duration >= 180.0, "segment should respect min duration"


def test_semantic_merge_similarity_break():
    segments = []
    for idx in range(200):
        start = float(idx * 2)
        text = "alpha alpha" if idx < 120 else "beta beta"
        segments.append({"start": start, "end": start + 2.0, "text": text})
    transcript = {"segments": segments}
    with TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        ctx = _ctx(run_dir, transcript, {"segments": []})
        with _with_config(
            {
                "SEMANTIC_SEGMENT_MODE": True,
                "SEMANTIC_TARGET_DURATION": 300.0,
                "MIN_CLIP_DURATION": 180.0,
                "MAX_CLIP_DURATION": 600.0,
                "MIN_TARGET_CLIP_DURATION": 180.0,
                "SEMANTIC_SIMILARITY_THRESHOLD": 0.99,
                "SEMANTIC_MAX_TIME_GAP": 10.0,
            }
        ):
            result = semantic_spec.run(ctx)
        payload = result[ART_SEGMENTS_SEMANTIC]
        assert len(payload["segments"]) >= 2, "should split when similarity is low"
