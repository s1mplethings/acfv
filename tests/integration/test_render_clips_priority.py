from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from acfv.modular.artifact import coerce_output, producer_record
from acfv.modular.contracts import ART_AUDIO_HOST, ART_SEGMENTS_LLM, ART_SEGMENTS_SEMANTIC, ART_TRANSCRIPT, ART_VIDEO
from acfv.modular.plugins.render_clips import spec as render_spec
from acfv.modular.store import ArtifactStore
from acfv.modular.types import ArtifactEnvelope, ModuleContext


def test_render_clips_falls_back_to_semantic_when_llm_payload_empty(monkeypatch):
    def _fake_cut_video(input_path, output_path, start_time, duration):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"fake-clip")

    monkeypatch.setattr("acfv.modular.plugins.render_clips.cut_video_ffmpeg", _fake_cut_video)

    with TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        store = ArtifactStore(run_dir)
        semantic_env = coerce_output(
            ART_SEGMENTS_SEMANTIC,
            {
                "schema_version": "1.0.0",
                "units": "ms",
                "segments": [{"start_ms": 2000, "end_ms": 7000, "score": 3.0, "rank": 1}],
                "policy": {"target_duration_ms": 5000},
            },
            producer=producer_record("semantic_merge", "1", "x"),
            fingerprint="semantic-fp",
        )
        store.write_artifact(semantic_env)

        video_path = run_dir / "video.mp4"
        video_path.write_bytes(b"fake")
        inputs = {
            ART_VIDEO: ArtifactEnvelope(artifact_id="video", type=ART_VIDEO, payload={"path": str(video_path)}),
            ART_SEGMENTS_LLM: ArtifactEnvelope(artifact_id="llm", type=ART_SEGMENTS_LLM, payload={}),
            ART_AUDIO_HOST: ArtifactEnvelope(artifact_id="host", type=ART_AUDIO_HOST, payload={"path": None}),
            ART_TRANSCRIPT: ArtifactEnvelope(artifact_id="transcript", type=ART_TRANSCRIPT, payload={"segments": []}),
        }
        ctx = ModuleContext(inputs=inputs, params={"output_dir": str(run_dir / "clips")}, store=store, run_id=run_dir.name)
        result = render_spec.run(ctx)
        selected_segments = json.loads((run_dir / "work" / "selected_segments.json").read_text(encoding="utf-8"))

    assert ART_SEGMENTS_LLM not in result
    assert selected_segments["segments"][0]["start_ms"] == 2000
    assert selected_segments["segments"][0]["score"] == 3.0
