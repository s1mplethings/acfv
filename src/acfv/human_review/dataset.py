from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import random
from typing import Any, Iterable

from acfv.runtime.storage import storage_root

from .models import ReviewSample, ReviewTask


DATASET_VERSION = "fixed37-human-review-v4"
DEFAULT_SEED = 37012026


@dataclass(frozen=True)
class DatasetBuildResult:
    samples: tuple[ReviewSample, ...]
    metadata: dict[str, Any]
    missing_sources: tuple[str, ...]

    @property
    def counts(self) -> dict[str, int]:
        counts = {task.value: 0 for task in ReviewTask}
        for sample in self.samples:
            counts[sample.task.value] += 1
        return counts


class HumanReviewDatasetBuilder:
    """Read-only adapter from canonical evidence to typed review samples."""

    def __init__(self, source_root: Path | None = None, *, seed: int = DEFAULT_SEED) -> None:
        self._source_root_explicit = source_root is not None
        self.source_root = Path(source_root).resolve() if source_root else self.discover_source_root()
        self.seed = int(seed)
        self._media_index: dict[str, Path] | None = None

    @staticmethod
    def discover_source_root() -> Path | None:
        explicit = os.environ.get("ACFV_HUMAN_REVIEW_SOURCE_ROOT", "").strip()
        if explicit and Path(explicit).exists():
            return Path(explicit).resolve()
        candidates = [storage_root(), storage_root().parent, Path.cwd()]
        markers = (
            Path("generation-quality-repair-fixed37/manual-review"),
            Path("manual-review/asr-human-ground-truth-pack"),
        )
        for candidate in candidates:
            for parent in (candidate, *candidate.parents[:2]):
                if any((parent / marker).exists() for marker in markers):
                    return parent.resolve()
        return None

    def _find(self, relative: str, name: str | None = None) -> Path | None:
        if self.source_root is None:
            return None
        direct = self.source_root / relative
        if direct.exists():
            return direct
        target = name or Path(relative).name
        try:
            return next(self.source_root.rglob(target))
        except StopIteration:
            return None

    @staticmethod
    def _read_json(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8-sig"))

    @staticmethod
    def _csv(path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    def _safe_media(self, value: str) -> str:
        value = str(value or "").strip()
        if not value or value.startswith("NOT_AVAILABLE:"):
            return ""
        candidate = Path(value)
        if candidate.is_file():
            return str(candidate)
        if self.source_root:
            if self._media_index is None:
                self._media_index = {
                    path.name: path for pattern in ("*.mp4", "*.wav", "*.mkv", "*.webm")
                    for path in self.source_root.rglob(pattern)
                }
            relocated = self._media_index.get(candidate.name)
            if relocated:
                return str(relocated)
        return value

    def build(self) -> DatasetBuildResult:
        samples: list[ReviewSample] = []
        missing: list[str] = []
        source_files: list[Path] = []
        source_dataset_ids: set[str] = set()

        def require(relative: str, label: str, name: str | None = None) -> Path | None:
            path = self._find(relative, name)
            if path is None:
                missing.append(label)
            else:
                source_files.append(path)
            return path

        manual = Path("generation-quality-repair-fixed37/manual-review")
        asr_pack = require(str(manual / "asr-human-ground-truth-pack"), "ASR ground truth pack")
        if asr_pack:
            for metadata_path in sorted(asr_pack.glob("asr-*/metadata.json")):
                data = self._read_json(metadata_path)
                sample_id = f"asr-pack:{data.get('sample_id', metadata_path.parent.name)}"
                word = data.get("word") or {}
                context_path = metadata_path.parent / "context.txt"
                final_path = metadata_path.parent / "final.txt"
                samples.append(ReviewSample(
                    sample_id=sample_id,
                    task=ReviewTask.ASR,
                    creator=str(data.get("creator", "")),
                    content_type=str(data.get("content_type", "")),
                    title=f"ASR · {data.get('sample_id', metadata_path.parent.name)}",
                    media_a=str(metadata_path.parent / "audio.wav"),
                    start_ms=int(data.get("start_ms", word.get("start_ms", 0)) or 0),
                    end_ms=int(data.get("end_ms", word.get("end_ms", 0)) or 0),
                    prompt={
                        "current_asr": str(word.get("text", "")),
                        "context": context_path.read_text(encoding="utf-8", errors="replace") if context_path.exists() else "",
                        "final_transcript": final_path.read_text(encoding="utf-8", errors="replace") if final_path.exists() else "",
                    },
                    private={"confidence": word.get("confidence"), "selection": data.get("selection", "")},
                    source_path=str(metadata_path),
                ))

        asr100 = require(
            "generation-quality-review-bundle-generation-quality-v2/reports/asr-100-span-review-set.json",
            "ASR 100-span set",
            "asr-100-span-review-set.json",
        )
        if asr100:
            data = self._read_json(asr100)
            for index, item in enumerate(data.get("samples", []), 1):
                relative_audio = str(item.get("audio", ""))
                audio = asr100.parent.parent / relative_audio if relative_audio else Path()
                samples.append(ReviewSample(
                    sample_id=f"asr-span:{index:03d}:{item.get('event_id', '')[:8]}",
                    task=ReviewTask.ASR,
                    creator=str(item.get("creator", "")),
                    title=f"ASR span · {index:03d}",
                    media_a=str(audio) if relative_audio else str(item.get("output", "")),
                    start_ms=int(item.get("word_start_ms", 0) or 0),
                    end_ms=int(item.get("word_end_ms", 0) or 0),
                    prompt={
                        "current_asr": str(item.get("word", "")),
                        "context": str(item.get("context", "")),
                        "final_transcript": str(item.get("final_transcript", "")),
                    },
                    private={"confidence": item.get("confidence"), "sample_class": item.get("sample_class", "")},
                    source_path=str(asr100),
                ))

        blind = require(
            str(manual / "translation-human-review-pack/translation-blind-review.csv"),
            "translation blind set",
            "translation-blind-review.csv",
        )
        provider = self._find(str(manual / "translation-human-review-pack/translation-provider-evidence.csv"), "translation-provider-evidence.csv")
        provider_rows = {row.get("group_id", ""): row for row in self._csv(provider)} if provider else {}
        if blind:
            for blind_index, row in enumerate(self._csv(blind), 1):
                group_id = row.get("group_id", "")
                hidden = provider_rows.get(group_id, {})
                original = ReviewSample(
                    sample_id=f"translation:{group_id}",
                    task=ReviewTask.TRANSLATION,
                    title=f"Translation · {group_id}",
                    prompt={"source": row.get("source", ""), "context": row.get("context", ""), "a": row.get("A", ""), "b": row.get("B", "")},
                    private={
                        "pair_id": group_id,
                        "provider_a": hidden.get("blind_A_provider", ""),
                        "provider_b": hidden.get("blind_B_provider", ""),
                        "event_id": hidden.get("event_id", ""),
                    },
                    source_path=str(blind),
                )
                samples.append(original)
                # Forty deliberate, labelled consistency controls bring the
                # fixed blind set to the 120-sample Large profile. A/B is
                # swapped and the formal pair identity remains unique.
                if blind_index <= 40:
                    samples.append(ReviewSample(
                        sample_id=f"translation:control:{group_id}",
                        task=ReviewTask.TRANSLATION,
                        title=f"Translation · control {group_id}",
                        prompt={"source": row.get("source", ""), "context": row.get("context", ""), "a": row.get("B", ""), "b": row.get("A", "")},
                        private={
                            "pair_id": f"control:{group_id}", "base_pair_id": group_id,
                            "provider_a": hidden.get("blind_B_provider", ""), "provider_b": hidden.get("blind_A_provider", ""),
                            "event_id": hidden.get("event_id", ""),
                        },
                        source_path=str(blind),
                        consistency_control=True,
                    ))

        boundary = require(str(manual / "boundary-manual-review.csv"), "Fixed37 boundary set", "boundary-manual-review.csv")
        watch = require(str(manual / "watchability-pairwise-review.csv"), "watchability pairs", "watchability-pairwise-review.csv")
        watch_rows = {row.get("event_id", ""): row for row in self._csv(watch)} if watch else {}
        fixed_events_path = self._find(
            "generation-quality-review-bundle-generation-quality-v2/reports/fixed-event-set.json",
            "fixed-event-set.json",
        )
        fixed_events: dict[str, dict[str, Any]] = {}
        if fixed_events_path:
            source_files.append(fixed_events_path)
            payload = self._read_json(fixed_events_path)
            fixed_events = {str(item.get("event_id", "")): item for item in payload.get("events", [])}
        if boundary:
            for row in self._csv(boundary):
                event_id = row.get("event_id", "")
                event = fixed_events.get(event_id, {})
                boundary_info = event.get("standard_boundary_v1") or {}
                samples.append(ReviewSample(
                    sample_id=f"boundary:{event_id}",
                    task=ReviewTask.BOUNDARY,
                    creator=str(event.get("creator", "")),
                    content_type=str(event.get("content_type", "")),
                    title=str(event.get("recording_title", event_id[:8])),
                    media_a=self._safe_media(event.get("media_path", "")) or self._safe_media(watch_rows.get(event_id, {}).get("candidate_B", "")) or self._safe_media(watch_rows.get(event_id, {}).get("candidate_A", "")),
                    start_ms=int(boundary_info.get("start_ms", event.get("moment_start_ms", 0)) or 0),
                    end_ms=int(boundary_info.get("end_ms", event.get("moment_end_ms", 0)) or 0),
                    prompt={"summary": event.get("summary", ""), "transcript": event.get("transcript", ""), "event_id": event_id},
                    private={"recording_id": event.get("recording_id", ""), "strategy": event.get("discovery_source", "")},
                    source_path=str(boundary),
                ))

        configured_v4 = os.environ.get("ACFV_CREATOR_ADAPTIVE_REVIEW_V4", "").strip()
        configured_v2 = os.environ.get("ACFV_CREATOR_ADAPTIVE_REVIEW_V2", "").strip()
        local_new_twitch = [] if self._source_root_explicit else sorted(
            Path.cwd().glob("var/new-twitch-validation/human-review/human-review-v4.json")
        )
        local_v4 = [] if self._source_root_explicit else sorted(Path.cwd().glob("var/creator-adaptive-v3-real/human-review-v4.json"))
        local_v2 = [] if self._source_root_explicit else sorted(Path.cwd().glob("var/creator-adaptive-validation-v*/creator-adaptive-review-v2.json"))
        adaptive_review = (
            (Path(configured_v4).expanduser().resolve() if configured_v4 and Path(configured_v4).is_file() else None)
            or (local_new_twitch[-1] if local_new_twitch else None)
            or (local_v4[-1] if local_v4 else None)
            or self._find("evidence/validation/human-review-v4.json", "human-review-v4.json")
            or (Path(configured_v2).expanduser().resolve() if configured_v2 and Path(configured_v2).is_file() else None)
            or (local_v2[-1] if local_v2 else None)
            or self._find(
            "evidence/validation/creator-adaptive-review-v2.json",
            "creator-adaptive-review-v2.json",
            )
        )
        if adaptive_review:
            source_files.append(adaptive_review)
            payload = self._read_json(adaptive_review)
            if payload.get("dataset_id"):
                source_dataset_ids.add(str(payload["dataset_id"]))
            review_version = int(payload.get("schema_version", 2))
            for index, item in enumerate(payload.get("identity", []), 1):
                samples.append(ReviewSample(
                    sample_id=f"identity:v{review_version}:{item.get('id', index)}",
                    task=ReviewTask.IDENTITY,
                    creator=str(item.get("creator", "")), content_type=str(item.get("content_type", "")),
                    title=f"Identity · {index:03d}", media_a=self._safe_media(item.get("media", "")),
                    start_ms=int(item.get("start_ms", 0)), end_ms=int(item.get("end_ms", 0)),
                    prompt={"predicted_creator": item.get("predicted_creator", "Unknown"), "context": item.get("context", "")},
                    private={
                        "creator_id": item.get("creator_id", ""), "recording_id": item.get("recording_id", ""),
                        "profile_version": item.get("profile_version", "creator_profile_v1"),
                        "visual_score": item.get("visual_score"), "voice_score": item.get("voice_score"),
                    }, source_path=str(adaptive_review),
                ))
            for index, item in enumerate(payload.get("trusted_speech", []), 1):
                samples.append(ReviewSample(
                    sample_id=f"trusted-speech:v{review_version}:{item.get('id', index)}",
                    task=ReviewTask.TRUSTED_SPEECH,
                    creator=str(item.get("creator", "")), content_type=str(item.get("content_type", "")),
                    title=f"Trusted Speech · {index:03d}", media_a=self._safe_media(item.get("media", "")),
                    start_ms=int(item.get("start_ms", 0)), end_ms=int(item.get("end_ms", 0)),
                    prompt={
                        "predicted_creator": item.get("predicted_creator", "Unknown"),
                        "transcript": item.get("transcript", ""), "context": item.get("context", ""),
                    },
                    private={
                        "creator_id": item.get("creator_id", ""), "recording_id": item.get("recording_id", ""),
                        "profile_version": item.get("profile_version", "creator_profile_v2"),
                        "trusted_speech_unit_id": item.get("trusted_speech_unit_id", item.get("id", "")),
                    }, source_path=str(adaptive_review),
                ))
            for index, item in enumerate(payload.get("adaptive_asr", []), 1):
                swap = bool(random.Random(f"{self.seed}:{item.get('id', index)}").getrandbits(1))
                generic, adaptive = str(item.get("generic_text", "")), str(item.get("adaptive_text", ""))
                samples.append(ReviewSample(
                    sample_id=f"adaptive-asr:v{review_version}:{item.get('id', index)}",
                    task=ReviewTask.ADAPTIVE_ASR,
                    creator=str(item.get("creator", "")), content_type=str(item.get("content_type", "")),
                    title=f"Adaptive ASR · {index:03d}", media_a=self._safe_media(item.get("media", "")),
                    start_ms=int(item.get("start_ms", 0)), end_ms=int(item.get("end_ms", 0)),
                    prompt={"context": item.get("context", ""), "a": adaptive if swap else generic, "b": generic if swap else adaptive},
                    private={
                        "pair_id": str(item.get("id", index)), "strategy_a": "adaptive" if swap else "generic",
                        "strategy_b": "generic" if swap else "adaptive", "creator_id": item.get("creator_id", ""),
                        "recording_id": item.get("recording_id", ""),
                        "profile_version": item.get("profile_version", "creator_profile_v1"),
                    }, source_path=str(adaptive_review),
                ))

        if watch:
            for watch_index, row in enumerate(self._csv(watch), 1):
                event_id = row.get("event_id", "")
                event = fixed_events.get(event_id, {})
                original = ReviewSample(
                    sample_id=f"watchability:generation:{event_id}",
                    task=ReviewTask.WATCHABILITY,
                    creator=str(event.get("creator", "")),
                    content_type=str(row.get("content_type", event.get("content_type", ""))),
                    title=f"Watchability · {event_id[:8]}",
                    media_a=self._safe_media(row.get("candidate_A", "")),
                    media_b=self._safe_media(row.get("candidate_B", "")),
                    prompt={"comparison": "A / B"},
                    private={"pair_id": f"generation:{event_id}", "strategy_a": "baseline", "strategy_b": "fixed37"},
                    source_path=str(watch),
                )
                samples.append(original)
                if watch_index <= 31:
                    samples.append(ReviewSample(
                        sample_id=f"watchability:control:{event_id}",
                        task=ReviewTask.WATCHABILITY,
                        creator=str(event.get("creator", "")),
                        content_type=str(row.get("content_type", event.get("content_type", ""))),
                        title=f"Watchability · control {event_id[:8]}",
                        media_a=original.media_b, media_b=original.media_a,
                        prompt={"comparison": "A / B"},
                        private={"pair_id": f"control:{event_id}", "base_pair_id": f"generation:{event_id}", "strategy_a": "fixed37", "strategy_b": "baseline"},
                        source_path=str(watch),
                        consistency_control=True,
                    ))
                final_dir = self._find(f"generation-quality-repair-fixed37/final-clips", "final-clips")
                if final_dir:
                    event_dirs = list(final_dir.glob(f"*-{event_id[:8]}"))
                    if event_dirs:
                        short = next(event_dirs[0].glob("short/**/*.mp4"), None)
                        standard = next(event_dirs[0].glob("standard/**/*.mp4"), None)
                        if short and standard:
                            samples.append(ReviewSample(
                                sample_id=f"watchability:profile:{event_id}",
                                task=ReviewTask.WATCHABILITY,
                                creator=str(event.get("creator", "")),
                                content_type=str(event.get("content_type", "")),
                                title=f"Profile comparison · {event_id[:8]}",
                                media_a=str(short), media_b=str(standard),
                                prompt={"comparison": "A / B"},
                                private={"pair_id": f"profile:{event_id}", "strategy_a": "SHORT", "strategy_b": "STANDARD"},
                                source_path=str(final_dir),
                            ))

        cues = require(
            "generation-quality-review-bundle-generation-quality-v2/reports/semantic-cue-review-set.json",
            "subtitle cue set",
            "semantic-cue-review-set.json",
        )
        if cues:
            for index, item in enumerate(self._read_json(cues).get("cues", []), 1):
                samples.append(ReviewSample(
                    sample_id=f"subtitle:cue:{index:03d}:{str(item.get('event_id', ''))[:8]}",
                    task=ReviewTask.SUBTITLE,
                    title=f"Subtitle cue · {index:03d}",
                    start_ms=int(item.get("start_ms", 0) or 0),
                    end_ms=int(item.get("end_ms", 0) or 0),
                    prompt={"mode": "cue", "english": item.get("source", ""), "chinese": item.get("translation", "") or ""},
                    private={"cps": item.get("cps"), "event_id": item.get("event_id", ""), "profile": item.get("profile", "")},
                    source_path=str(cues),
                ))

        final_dir = self._find("generation-quality-repair-fixed37/final-clips", "final-clips")
        if final_dir:
            clip_index = 0
            for media in sorted(final_dir.glob("*/**/*.mp4")):
                if "revisions" in media.parts or clip_index >= 118:
                    continue
                clip_index += 1
                event_key = media.parts[-3] if len(media.parts) >= 3 else media.stem
                samples.append(ReviewSample(
                    sample_id=f"subtitle:clip:{clip_index:03d}:{hashlib.sha1(str(media).encode()).hexdigest()[:8]}",
                    task=ReviewTask.SUBTITLE,
                    title=f"Clip subtitle · {event_key}",
                    media_a=str(media),
                    prompt={"mode": "clip"},
                    private={"profile": media.parent.name},
                    source_path=str(media),
                ))

        if boundary:
            for row in self._csv(boundary):
                event_id = row.get("event_id", "")
                event = fixed_events.get(event_id, {})
                media = self._safe_media(watch_rows.get(event_id, {}).get("candidate_B", "")) or self._safe_media(watch_rows.get(event_id, {}).get("candidate_A", ""))
                samples.append(ReviewSample(
                    sample_id=f"publishability:{event_id}",
                    task=ReviewTask.PUBLISHABILITY,
                    creator=str(event.get("creator", "")),
                    content_type=str(event.get("content_type", "")),
                    title=f"Publishability · {event_id[:8]}",
                    media_a=media,
                    prompt={"summary": event.get("summary", "")},
                    private={"event_id": event_id, "strategy": "fixed37"},
                    source_path=str(boundary),
                ))

        # Stable deterministic order without leaking A/B identities.
        rng = random.Random(self.seed)
        by_task: dict[ReviewTask, list[ReviewSample]] = {task: [] for task in ReviewTask}
        for sample in samples:
            by_task[sample.task].append(sample)
        ordered: list[ReviewSample] = []
        for task in ReviewTask:
            group = by_task[task]
            rng.shuffle(group)
            ordered.extend(group)
        identifiers = [item.sample_id for item in ordered]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("dataset contains duplicate sample IDs")
        digest = hashlib.sha256()
        for path in sorted(set(source_files)):
            digest.update(str(path).encode("utf-8"))
            if path.is_file():
                digest.update(path.read_bytes())
        metadata = {
            "dataset_version": DATASET_VERSION,
            "source_dataset_ids": sorted(source_dataset_ids),
            "active_dataset_id": next(iter(source_dataset_ids)) if len(source_dataset_ids) == 1 else "COMBINED",
            "fixed37_hash": digest.hexdigest(),
            "random_seed": self.seed,
            "source_root": str(self.source_root or ""),
            "media_available": sum(bool(item.media_a) and Path(item.media_a).exists() for item in ordered),
            "sample_count": len(ordered),
            "counts": {task.value: len(by_task[task]) for task in ReviewTask},
            "missing_sources": missing,
        }
        return DatasetBuildResult(tuple(ordered), metadata, tuple(missing))
