from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from acfv.creator_adaptive.models import AvatarIdentityObservation

from .model import CreatorVisualIdentityService


def verify_file_sha256(path: Path, expected: str) -> None:
    """Fail closed when a configured model dependency is not the audited file."""
    expected = str(expected or "").strip().lower()
    if not expected:
        raise ValueError(f"Missing SHA-256 for model dependency: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected:
        raise ValueError(f"Model dependency SHA-256 mismatch: {path}")


def calibrated_observation_confidence(prediction: Any) -> float:
    """Map a thresholded identity decision to fusion confidence.

    Raw classifier probability, margin, and support remain in metadata.  This
    value describes the calibrated decision state consumed by temporal fusion,
    not the binary classifier's softmax probability.
    """
    if prediction.state.value == "STRONG":
        return min(1.0, .85 + max(0.0, float(prediction.margin)) * .15)
    if prediction.state.value == "PROBABLE":
        return min(.84, .65 + max(0.0, float(prediction.margin)) * .20)
    return 0.0


class TwoStageCreatorVisualIdentityProvider:
    """Compose presence bbox detection with open-set crop identity."""

    def __init__(self, presence_provider: Any, identity_service: CreatorVisualIdentityService, *, crop_padding: float = .08, min_presence_confidence: float = .70) -> None:
        self.presence_provider = presence_provider
        self.identity_service = identity_service
        self.crop_padding = float(crop_padding)
        self.min_presence_confidence = float(min_presence_confidence)

    @property
    def model_version(self) -> str:
        return f"{self.presence_provider.model_version}+{self.identity_service.model.model_version}"

    def identify_frame(self, frame: Any, timestamp_ms: int) -> list[AvatarIdentityObservation]:
        presence = list(self.presence_provider.identify_frame(frame, timestamp_ms) or ())
        crops, usable = [], []
        height, width = frame.shape[:2]
        for row in presence:
            if not row.bbox or row.confidence < self.min_presence_confidence:
                continue
            x1, y1, x2, y2 = row.bbox
            padding_x, padding_y = (x2 - x1) * self.crop_padding, (y2 - y1) * self.crop_padding
            left, top = max(0, int(x1 - padding_x)), max(0, int(y1 - padding_y))
            right, bottom = min(width, int(x2 + padding_x)), min(height, int(y2 + padding_y))
            crop = frame[top:bottom, left:right]
            if crop.size:
                crops.append(crop); usable.append(row)
        if not crops:
            return []
        predictions = self.identity_service.identify_crops(crops)
        observations = []
        for presence_row, prediction in zip(usable, predictions):
            label = prediction.creator_id or prediction.state.value.lower()
            observations.append(AvatarIdentityObservation(
                creator_external_id=label,
                confidence=calibrated_observation_confidence(prediction),
                timestamp_ms=int(timestamp_ms), model_version=self.model_version,
                provider="two-stage-creator-visual-identity", frame_quality=presence_row.frame_quality,
                bbox=presence_row.bbox, track_id=presence_row.track_id,
                raw_metadata={
                    "raw_presence_label": presence_row.creator_external_id,
                    "presence_confidence": presence_row.confidence,
                    "identity_state": prediction.state.value,
                    "identity_score": prediction.score,
                    "identity_margin": prediction.margin,
                    "identity_support": prediction.support_score,
                    "second_creator_id": prediction.second_creator_id,
                    "prototype_id": prediction.prototype_id,
                    "encoder_version": self.identity_service.encoder.model_version,
                    "detector_version": presence_row.model_version,
                    "identity_model_version": prediction.model_version,
                },
            ))
        return observations


def load_creator_visual_provider(presence_provider: Any, config_path: Path | None = None) -> TwoStageCreatorVisualIdentityProvider:
    """Load the selected single-encoder visual identity provider from config."""
    from .encoders import TorchvisionEncoder
    from .model import LinearProbeIdentityModel

    project = Path.cwd().resolve()
    config = Path(config_path or os.environ.get("ACFV_CREATOR_VISUAL_CONFIG", "") or project / "config/creator_visual_identity.json").expanduser().resolve()
    payload = json.loads(config.read_text(encoding="utf-8"))
    classifier = Path(str(payload["classifier_path"]))
    classifier = classifier if classifier.is_absolute() else project / classifier
    explicit_weights = os.environ.get("ACFV_CREATOR_VISUAL_ENCODER_WEIGHTS", "").strip()
    weights = Path(explicit_weights).expanduser() if explicit_weights else Path.home() / ".cache/torch/hub/checkpoints" / str(payload["encoder_weights_filename"])
    if not classifier.is_file() or not weights.is_file():
        raise FileNotFoundError(f"Creator visual model dependency missing: classifier={classifier.is_file()} encoder={weights.is_file()}")
    verify_file_sha256(classifier, str(payload.get("classifier_sha256", "")))
    verify_file_sha256(weights, str(payload.get("encoder_weights_sha256", "")))
    encoder = TorchvisionEncoder(weights_path=weights)
    model = LinearProbeIdentityModel.load(classifier)
    return TwoStageCreatorVisualIdentityProvider(presence_provider, CreatorVisualIdentityService(encoder, model))
