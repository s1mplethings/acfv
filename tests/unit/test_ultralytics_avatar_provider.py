from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from acfv.providers.ultralytics_avatar import UltralyticsAvatarProvider


class Value:
    def __init__(self, value): self.value = value
    def item(self): return self.value
    def __getitem__(self, _): return self
    def tolist(self): return list(self.value)


def test_provider_preserves_presence_label_and_does_not_claim_identity(tmp_path: Path) -> None:
    model = tmp_path / "best.pt"; model.write_bytes(b"weights")
    provider = UltralyticsAvatarProvider(model)
    box = SimpleNamespace(cls=Value(0), conf=Value(.91), xyxy=Value((1, 2, 30, 40)))
    result = SimpleNamespace(boxes=[box], names={0: "vtuber"})
    rows = provider._normalize(result, 1234)
    assert rows[0]["label"] == "vtuber"
    assert rows[0]["raw_metadata"]["identity_capable"] is False
    assert rows[0]["bbox"] == (1.0, 2.0, 30.0, 40.0)


def test_provider_rejects_missing_model_and_mismatched_batch(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        UltralyticsAvatarProvider(tmp_path / "missing.pt")
    model = tmp_path / "best.pt"; model.write_bytes(b"weights")
    with pytest.raises(ValueError):
        UltralyticsAvatarProvider(model).identify_frames([object()], [])
