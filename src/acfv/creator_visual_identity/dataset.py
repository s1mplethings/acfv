from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np

from acfv.creator_adaptive.final_holdout import FinalHoldoutRecord, assert_not_final_holdout


VALID_SPLITS = {"train", "validation", "holdout", "unknown"}


@dataclass(frozen=True)
class RecordingSource:
    creator_id: str | None
    recording_id: str
    path: Path
    split: str
    single_creator_confirmed: bool = False
    collab: bool = False
    sample_fps: float = 2.0
    group_id: str = ""
    allow_full_frame_unknown: bool = False


@dataclass(frozen=True)
class VisualCropSample:
    sample_id: str
    creator_id: str | None
    recording_id: str
    timestamp_ms: int
    bbox: tuple[float, float, float, float]
    detector_confidence: float
    source_resolution: tuple[int, int]
    crop_resolution: tuple[int, int]
    detector_model_hash: str
    dataset_split: str
    track_group_id: str
    quality: float
    source_frame_hash: str
    crop_path: str
    source_path: str
    label_source: str

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("bbox", "source_resolution", "crop_resolution"):
            value[key] = list(value[key])
        return value


def difference_hash(image: np.ndarray, size: int = 8) -> int:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    resized = cv2.resize(gray, (size + 1, size), interpolation=cv2.INTER_AREA)
    bits = resized[:, 1:] > resized[:, :-1]
    result = 0
    for bit in bits.flat:
        result = (result << 1) | int(bit)
    return result


def hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


class CreatorVisualDatasetBuilder:
    """Builds provenance-complete crops without recording/time leakage.

    ``presence_provider`` must expose ``model_version`` and
    ``identify_frame(frame, timestamp_ms)``.  Recording ownership is accepted as
    a weak auto-label only when the caller explicitly marks a source as a
    single-creator, non-collab recording and the detector finds one dominant box.
    """

    def __init__(
        self, presence_provider: Any, output_root: Path, *, min_detector_confidence: float = .70,
        min_area_ratio: float = .025, max_area_ratio: float = .90,
        min_aspect: float = .20, max_aspect: float = 3.0,
        dedup_hamming: int = 4, crop_padding: float = .08,
        dataset_version: str = "creator-visual-v1",
        inference_batch_size: int = 32,
        final_holdouts: Iterable[FinalHoldoutRecord] = (),
        leakage_event_path: Path | None = None,
    ) -> None:
        self.provider = presence_provider
        self.output_root = Path(output_root).resolve()
        self.min_detector_confidence = min_detector_confidence
        self.min_area_ratio = min_area_ratio
        self.max_area_ratio = max_area_ratio
        self.min_aspect = min_aspect
        self.max_aspect = max_aspect
        self.dedup_hamming = dedup_hamming
        self.crop_padding = crop_padding
        self.dataset_version = dataset_version
        self.inference_batch_size = max(1, int(inference_batch_size))
        self.final_holdouts = tuple(final_holdouts)
        self.leakage_event_path = Path(leakage_event_path) if leakage_event_path else None

    @staticmethod
    def validate_sources(sources: Iterable[RecordingSource]) -> list[RecordingSource]:
        rows = list(sources)
        seen_recordings: dict[str, str] = {}
        seen_paths: dict[Path, str] = {}
        for source in rows:
            if source.split not in VALID_SPLITS:
                raise ValueError(f"invalid dataset split: {source.split}")
            resolved = Path(source.path).resolve()
            if not resolved.is_file():
                raise FileNotFoundError(resolved)
            old_split = seen_recordings.setdefault(source.recording_id, source.split)
            if old_split != source.split:
                raise ValueError(f"recording leakage: {source.recording_id} in {old_split} and {source.split}")
            old_path_split = seen_paths.setdefault(resolved, source.split)
            if old_path_split != source.split:
                raise ValueError(f"source path leakage: {resolved} in {old_path_split} and {source.split}")
            if source.creator_id and (not source.single_creator_confirmed or source.collab):
                raise ValueError(f"unsafe auto-label source: {source.recording_id}")
            if source.sample_fps <= 0:
                raise ValueError("sample_fps must be positive")
        return rows

    def build(self, sources: Iterable[RecordingSource], *, max_samples_per_recording: int | None = None) -> dict[str, Any]:
        candidate_rows = list(sources)
        for source in candidate_rows:
            operation = "visual_train" if source.split == "train" else "visual_threshold_tuning"
            assert_not_final_holdout(
                source.recording_id,
                self.final_holdouts,
                operation=operation,
                leakage_event_path=self.leakage_event_path,
            )
        rows = self.validate_sources(candidate_rows)
        self.output_root.mkdir(parents=True, exist_ok=True)
        samples: list[VisualCropSample] = []
        rejections: dict[str, int] = {}
        source_reports: list[dict[str, Any]] = []
        for source in rows:
            accepted, rejected = self._build_source(source, max_samples_per_recording=max_samples_per_recording)
            samples.extend(accepted)
            source_reports.append({
                "creator_id": source.creator_id, "recording_id": source.recording_id,
                "split": source.split, "source_path": str(Path(source.path).resolve()),
                "accepted": len(accepted), "rejections": rejected,
            })
            for reason, count in rejected.items():
                rejections[reason] = rejections.get(reason, 0) + count
        manifest_path = self.output_root / "visual-dataset-manifest.jsonl"
        manifest_path.write_text(
            "\n".join(json.dumps(sample.as_dict(), ensure_ascii=False, sort_keys=True) for sample in samples) + ("\n" if samples else ""),
            encoding="utf-8",
        )
        digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        counts: dict[str, int] = {}
        for sample in samples:
            key = f"{sample.creator_id or 'UNKNOWN'}:{sample.dataset_split}"
            counts[key] = counts.get(key, 0) + 1
        report = {
            "dataset_version": self.dataset_version, "manifest": str(manifest_path),
            "manifest_sha256": digest, "samples": len(samples), "counts": counts,
            "recordings": len(rows), "rejections": rejections,
            "source_reports": source_reports,
            "split_unit": "recording_id", "recording_leakage": False,
            "detector_model_version": str(getattr(self.provider, "model_version", "unknown")),
            "auto_label_policy": "explicit single-creator + one dominant high-quality avatar bbox",
        }
        (self.output_root / "visual-dataset-audit.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return report

    def _build_source(self, source: RecordingSource, *, max_samples_per_recording: int | None) -> tuple[list[VisualCropSample], dict[str, int]]:
        capture = cv2.VideoCapture(str(source.path))
        if not capture.isOpened():
            raise RuntimeError(f"cannot open source video: {source.path}")
        native_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if native_fps <= 0:
            capture.release()
            raise RuntimeError(f"invalid video fps: {source.path}")
        stride = max(1, int(round(native_fps / source.sample_fps)))
        accepted: list[VisualCropSample] = []
        rejected: dict[str, int] = {}
        recent_hashes: list[int] = []
        pending: list[tuple[np.ndarray, int]] = []
        frame_index = 0

        def flush_pending() -> bool:
            if not pending:
                return False
            frames = [item[0] for item in pending]
            timestamps = [item[1] for item in pending]
            identify_frames = getattr(self.provider, "identify_frames", None)
            if callable(identify_frames):
                observation_rows = list(identify_frames(frames, timestamps))
            else:
                observation_rows = [
                    list(self.provider.identify_frame(frame, timestamp) or ())
                    for frame, timestamp in pending
                ]
            if len(observation_rows) != len(pending):
                raise RuntimeError("presence provider batch result count mismatch")
            for (frame, timestamp_ms), observations in zip(pending, observation_rows):
                candidates = [row for row in observations if float(getattr(row, "confidence", 0.0)) >= self.min_detector_confidence]
                if not candidates and source.creator_id is None and source.allow_full_frame_unknown:
                    from types import SimpleNamespace
                    height, width = frame.shape[:2]
                    candidates = [SimpleNamespace(confidence=0.0, bbox=(width * .05, height * .05, width * .95, height * .95))]
                if len(candidates) != 1:
                    self._reject(rejected, "no_single_dominant_avatar"); continue
                observation = candidates[0]
                bbox = getattr(observation, "bbox", None)
                crop = self._crop(frame, bbox)
                if crop is None:
                    self._reject(rejected, "invalid_bbox_or_quality"); continue
                phash = difference_hash(crop)
                if any(hamming(phash, old) <= self.dedup_hamming for old in recent_hashes[-24:]):
                    self._reject(rejected, "near_duplicate"); continue
                recent_hashes.append(phash)
                frame_hash = hashlib.sha256(frame.tobytes()).hexdigest()
                identity = hashlib.sha256(f"{source.recording_id}:{timestamp_ms}:{frame_hash}".encode()).hexdigest()[:20]
                target = self.output_root / "crops" / source.split / (source.creator_id or "UNKNOWN") / f"{identity}.jpg"
                target.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(target), crop, [cv2.IMWRITE_JPEG_QUALITY, 94])
                height, width = frame.shape[:2]
                crop_height, crop_width = crop.shape[:2]
                image_quality = self._quality(crop)
                quality = image_quality * float(getattr(observation, "confidence", 0.0)) if source.creator_id else image_quality
                accepted.append(VisualCropSample(
                    sample_id=identity, creator_id=source.creator_id, recording_id=source.recording_id,
                    timestamp_ms=timestamp_ms, bbox=tuple(float(x) for x in bbox),
                    detector_confidence=float(observation.confidence), source_resolution=(width, height),
                    crop_resolution=(crop_width, crop_height), detector_model_hash=str(getattr(self.provider, "model_version", "unknown")),
                    dataset_split=source.split, track_group_id=source.group_id or source.recording_id,
                    quality=quality, source_frame_hash=frame_hash, crop_path=str(target), source_path=str(Path(source.path).resolve()),
                    label_source="recording_proxy_safe_gate" if source.creator_id else "unknown_challenge_avatar_crop",
                ))
                if max_samples_per_recording and len(accepted) >= max_samples_per_recording:
                    pending.clear()
                    return True
            pending.clear()
            return False

        try:
            while True:
                ok = capture.grab()
                if not ok:
                    break
                if frame_index % stride:
                    frame_index += 1
                    continue
                ok, frame = capture.retrieve()
                timestamp_ms = int(round(frame_index / native_fps * 1000))
                frame_index += 1
                if not ok or frame is None:
                    self._reject(rejected, "decode_failure"); continue
                pending.append((frame, timestamp_ms))
                if len(pending) >= self.inference_batch_size and flush_pending():
                    break
            flush_pending()
        finally:
            capture.release()
        return accepted, rejected

    @staticmethod
    def _reject(rows: dict[str, int], reason: str) -> None:
        rows[reason] = rows.get(reason, 0) + 1

    def _crop(self, frame: np.ndarray, bbox: Any) -> np.ndarray | None:
        if bbox is None or len(bbox) != 4:
            return None
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = (float(value) for value in bbox)
        box_width, box_height = x2 - x1, y2 - y1
        if box_width <= 1 or box_height <= 1:
            return None
        area_ratio = box_width * box_height / float(width * height)
        aspect = box_width / box_height
        if not self.min_area_ratio <= area_ratio <= self.max_area_ratio or not self.min_aspect <= aspect <= self.max_aspect:
            return None
        padding_x, padding_y = box_width * self.crop_padding, box_height * self.crop_padding
        left, top = max(0, int(x1 - padding_x)), max(0, int(y1 - padding_y))
        right, bottom = min(width, int(x2 + padding_x)), min(height, int(y2 + padding_y))
        crop = frame[top:bottom, left:right]
        if crop.size == 0 or min(crop.shape[:2]) < 48 or self._quality(crop) < .10:
            return None
        return crop

    @staticmethod
    def _quality(crop: np.ndarray) -> float:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        brightness = float(gray.mean()) / 255.0
        contrast = min(1.0, float(gray.std()) / 64.0)
        sharpness = min(1.0, float(cv2.Laplacian(gray, cv2.CV_64F).var()) / 500.0)
        exposure = max(0.0, 1.0 - abs(brightness - .5) * 1.5)
        return max(0.0, min(1.0, .4 * sharpness + .3 * contrast + .3 * exposure))
