from __future__ import annotations

from datetime import datetime

from acfv.modular.progress import ProgressEmitter


class _Store:
    def __init__(self) -> None:
        self.artifact = None

    def write_artifact(self, artifact) -> None:
        self.artifact = artifact


def test_progress_timestamp_is_explicit_utc() -> None:
    store = _Store()
    artifact = ProgressEmitter(store, "run-1").emit("transcribe", 1, 2)

    timestamp = artifact.payload["timestamp"]
    assert timestamp.endswith("Z")
    assert datetime.fromisoformat(timestamp.replace("Z", "+00:00")).utcoffset().total_seconds() == 0
    assert store.artifact is artifact
