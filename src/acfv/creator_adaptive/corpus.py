"""Frozen VOD-level split contracts for creator-adaptive validation corpora."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping

from .final_holdout import FinalHoldoutRecord, assert_not_final_holdout


class CorpusRole(str, Enum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    HOLDOUT = "HOLDOUT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CorpusVod:
    creator: str
    vod_id: str
    role: CorpusRole
    url: str = ""
    published_at: str = ""
    duration_seconds: int = 0
    vod_type: str = "archive"
    unknown_partition: str = ""


ABSOLUTELY_FORBIDDEN_MEMORY_ROLES = frozenset({CorpusRole.HOLDOUT, CorpusRole.UNKNOWN})
MEMORY_KINDS = frozenset({
    "visual_train", "voice_train", "trusted_speech", "lexicon",
    "acoustic_exemplar", "threshold_tuning",
})


def validate_vod_split(rows: Iterable[CorpusVod]) -> tuple[CorpusVod, ...]:
    frozen = tuple(rows)
    seen: dict[str, CorpusVod] = {}
    for row in frozen:
        vod_id = str(row.vod_id).strip()
        if not vod_id.isdigit():
            raise ValueError(f"invalid Twitch VOD ID: {row.vod_id!r}")
        prior = seen.get(vod_id)
        if prior is not None:
            raise ValueError(
                f"VOD-level leakage: {vod_id} appears in both {prior.role.value} and {row.role.value}"
            )
        if row.role is CorpusRole.UNKNOWN and not row.unknown_partition:
            raise ValueError(f"UNKNOWN VOD {vod_id} requires an unknown_partition")
        seen[vod_id] = row
    return frozen


def assert_memory_eligible(
    vod_id: str,
    split_by_vod: Mapping[str, CorpusRole | str],
    *,
    memory_kind: str,
    final_holdouts: Iterable[FinalHoldoutRecord] = (),
    leakage_event_path: Path | None = None,
) -> None:
    if memory_kind not in MEMORY_KINDS:
        raise ValueError(f"unsupported creator-memory kind: {memory_kind}")
    assert_not_final_holdout(
        vod_id, final_holdouts, operation=memory_kind,
        leakage_event_path=leakage_event_path,
    )
    if vod_id not in split_by_vod:
        raise ValueError(f"VOD {vod_id} is not present in the frozen split")
    role = CorpusRole(split_by_vod[vod_id])
    if role in ABSOLUTELY_FORBIDDEN_MEMORY_ROLES:
        raise PermissionError(f"{role.value} VOD {vod_id} cannot enter {memory_kind}")
    if role is CorpusRole.VALIDATION and memory_kind != "threshold_tuning":
        raise PermissionError(
            f"VALIDATION VOD {vod_id} is threshold-only and cannot enter {memory_kind}"
        )


def split_payload(
    rows: Iterable[CorpusVod],
    *,
    dataset_id: str,
    dataset_version: str,
) -> dict[str, object]:
    frozen = validate_vod_split(rows)
    body: dict[str, object] = {
        "schema_version": "1.0",
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "split_unit": "TWITCH_VOD_ID",
        "frozen_before_training": True,
        "leakage_guard": (
            "HOLDOUT and UNKNOWN cannot enter visual/voice training, trusted speech, "
            "lexicon, acoustic exemplars, or threshold tuning; VALIDATION is threshold-only."
        ),
        "rows": [
            {**asdict(row), "role": row.role.value}
            for row in sorted(frozen, key=lambda item: (item.role.value, item.creator.casefold(), item.vod_id))
        ],
    }
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    body["sha256"] = hashlib.sha256(canonical).hexdigest()
    return body


def write_frozen_split(path: Path, payload: Mapping[str, object]) -> str:
    expected = str(payload.get("sha256") or "")
    body = {key: value for key, value in payload.items() if key != "sha256"}
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    actual = hashlib.sha256(canonical).hexdigest()
    if not expected or expected != actual:
        raise ValueError("split SHA256 does not match canonical payload")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return actual
