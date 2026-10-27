from __future__ import annotations

"""Ultralytics adapter for the recovered ACFV avatar-presence detector.

The recovered checkpoint has one class, ``vtuber``.  This module deliberately
preserves that raw label: it detects avatar presence, but it does not infer a
creator identity.
"""

import hashlib
import os
from pathlib import Path
from typing import Any, Iterable


class UltralyticsAvatarProvider:
    def __init__(self, model_path: str | Path) -> None:
        self.path = Path(model_path).expanduser().resolve()
        if not self.path.is_file():
            raise FileNotFoundError(f"Avatar model does not exist: {self.path}")
        self._model: Any | None = None
        self._model_version = self._version()

    def _version(self) -> str:
        stat = self.path.stat()
        fingerprint = f"{self.path.name}:{stat.st_size}:{stat.st_mtime_ns}"
        return f"yolo-avatar-{hashlib.sha256(fingerprint.encode()).hexdigest()[:12]}"

    def _load(self) -> Any:
        if self._model is None:
            try:
                from ultralytics import YOLO
            except ImportError as exc:  # pragma: no cover - environment-specific
                raise RuntimeError("ultralytics is required for the recovered avatar model") from exc
            self._model = YOLO(str(self.path))
            names = dict(getattr(self._model, "names", {}) or {})
            if names != {0: "vtuber"}:
                raise RuntimeError(
                    "Recovered adapter only supports the audited single-class "
                    f"checkpoint {{0: 'vtuber'}}, got {names!r}"
                )
        return self._model

    @staticmethod
    def _device() -> str | int | None:
        value = os.environ.get("ACFV_AVATAR_DEVICE", "").strip()
        if not value or value.lower() == "auto":
            return None
        return int(value) if value.isdigit() else value

    @staticmethod
    def _confidence() -> float:
        try:
            return max(0.0, min(1.0, float(os.environ.get("ACFV_AVATAR_CONFIDENCE", "0.25"))))
        except ValueError:
            return 0.25

    def identify_frames(
        self, frames: Iterable[Any], timestamps_ms: Iterable[int]
    ) -> list[list[dict[str, Any]]]:
        frame_rows = list(frames)
        timestamps = [int(value) for value in timestamps_ms]
        if len(frame_rows) != len(timestamps):
            raise ValueError("frames and timestamps_ms must have equal lengths")
        if not frame_rows:
            return []
        kwargs: dict[str, Any] = {
            "source": frame_rows,
            "imgsz": 640,
            "conf": self._confidence(),
            "verbose": False,
        }
        device = self._device()
        if device is not None:
            kwargs["device"] = device
        results = self._load().predict(**kwargs)
        if len(results) != len(timestamps):
            raise RuntimeError(
                f"Avatar provider returned {len(results)} results for {len(timestamps)} frames"
            )
        return [self._normalize(result, timestamp) for result, timestamp in zip(results, timestamps)]

    def identify_frame(self, frame: Any, timestamp_ms: int) -> list[dict[str, Any]]:
        return self.identify_frames((frame,), (timestamp_ms,))[0]

    def _normalize(self, result: Any, timestamp_ms: int) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return observations
        names = dict(getattr(result, "names", {}) or {})
        for box in boxes:
            class_id = int(box.cls[0].item())
            label = str(names.get(class_id, class_id))
            coordinates = tuple(float(value) for value in box.xyxy[0].tolist())
            observations.append({
                "label": label,
                "confidence": float(box.conf[0].item()),
                "bbox": coordinates,
                "timestamp_ms": timestamp_ms,
                "model_version": self._model_version,
                "provider": "ultralytics-avatar-presence",
                "raw_metadata": {
                    "class_id": class_id,
                    "identity_capable": False,
                    "semantic": "avatar_presence",
                },
            })
        return observations


def create_provider(model_path: str | Path) -> UltralyticsAvatarProvider:
    return UltralyticsAvatarProvider(model_path)
