"""Immutable final-holdout lifecycle and leakage guards.

Final holdouts are evaluation-only. A reserved holdout may be claimed exactly
once after preflight; a consumed holdout remains permanently locked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
from typing import Iterable, Mapping


class FinalHoldoutState(str, Enum):
    RESERVED_UNOPENED = "RESERVED_UNOPENED"
    CONSUMED_LOCKED = "CONSUMED_LOCKED"


@dataclass(frozen=True)
class FinalHoldoutRecord:
    dataset_id: str
    vod_id: str
    state: FinalHoldoutState
    run_count: int
    ground_truth_opened: bool
    rerun_allowed: bool = False

    def __post_init__(self) -> None:
        if not self.dataset_id.strip() or not self.vod_id.strip():
            raise ValueError("final holdout requires dataset_id and vod_id")
        if self.run_count not in {0, 1}:
            raise ValueError("final holdout run_count must be 0 or 1")
        if self.rerun_allowed:
            raise ValueError("final holdout rerun_allowed must remain false")
        if self.state is FinalHoldoutState.RESERVED_UNOPENED:
            if self.run_count != 0 or self.ground_truth_opened:
                raise ValueError("reserved final holdout must be unopened with run_count=0")
        elif self.run_count != 1:
            raise ValueError("consumed final holdout must have run_count=1")


FINAL_HOLDOUT_PROHIBITED_OPERATIONS = frozenset({
    "visual_train", "visual_prototype", "visual_threshold_tuning",
    "voice_train", "voice_mode_clustering", "speaker_threshold_tuning",
    "trusted_speech", "lexicon", "acoustic_exemplar",
    "lexical_acoustic_memory", "adaptive_asr_context", "whisper_tuning",
    "hyperparameter_selection", "bug_quality_tuning", "model_selection",
    "human_calibration", "threshold_tuning",
})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _append_leakage_event(path: Path | None, *, record: FinalHoldoutRecord,
                          operation: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "event": "FINAL_HOLDOUT_LEAKAGE_ATTEMPT",
        "occurred_at": _utc_now(),
        "dataset_id": record.dataset_id,
        "vod_id": record.vod_id,
        "state": record.state.value,
        "operation": operation,
        "blocked": True,
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def assert_not_final_holdout(
    vod_id: str,
    records: Iterable[FinalHoldoutRecord],
    *,
    operation: str,
    leakage_event_path: Path | None = None,
) -> None:
    """Block every training/calibration use of a V1/V2 final-holdout VOD."""
    if operation not in FINAL_HOLDOUT_PROHIBITED_OPERATIONS:
        raise ValueError(f"unsupported final-holdout operation: {operation}")
    match = next((row for row in records if row.vod_id == str(vod_id)), None)
    if match is None:
        return
    _append_leakage_event(leakage_event_path, record=match, operation=operation)
    raise PermissionError(
        "FINAL_HOLDOUT_LEAKAGE_ATTEMPT: "
        f"{match.dataset_id} VOD {match.vod_id} is {match.state.value}; "
        f"blocked operation={operation}"
    )


def claim_final_holdout(
    records: Iterable[FinalHoldoutRecord],
    *,
    dataset_id: str,
    claim_path: Path,
    preflight_passed: bool,
) -> dict[str, object]:
    """Atomically claim one reserved dataset; an existing claim blocks reruns."""
    selected = tuple(row for row in records if row.dataset_id == dataset_id)
    if not selected:
        raise ValueError(f"unknown final holdout dataset: {dataset_id}")
    if not preflight_passed:
        raise PermissionError("final holdout preflight has not passed")
    if any(row.state is not FinalHoldoutState.RESERVED_UNOPENED for row in selected):
        raise PermissionError(f"final holdout {dataset_id} is already consumed and locked")
    claim = {
        "schema_version": "1.0",
        "dataset_id": dataset_id,
        "claimed_at": _utc_now(),
        "state": FinalHoldoutState.CONSUMED_LOCKED.value,
        "run_count": 1,
        "ground_truth_opened": False,
        "rerun_allowed": False,
        "vod_ids": sorted(row.vod_id for row in selected),
    }
    claim_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(claim_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(claim, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
    except BaseException:
        try:
            claim_path.unlink(missing_ok=True)
        finally:
            raise
    return claim


def records_from_manifest(payload: Mapping[str, object]) -> tuple[FinalHoldoutRecord, ...]:
    """Parse canonical V1/V2 rows without reading referenced media."""
    dataset_id = str(payload.get("dataset_id") or "")
    state = FinalHoldoutState(str(payload.get("state") or ""))
    run_count = int(payload.get("run_count", 0))
    ground_truth_opened = bool(payload.get("ground_truth_opened", False))
    rerun_allowed = bool(payload.get("rerun_allowed", False))
    rows = payload.get("rows") or payload.get("creators") or ()
    if not isinstance(rows, (list, tuple)):
        raise ValueError("final holdout manifest rows must be a list")
    records: list[FinalHoldoutRecord] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("final holdout manifest row must be an object")
        records.append(FinalHoldoutRecord(
            dataset_id=dataset_id,
            vod_id=str(row.get("vod_id") or ""),
            state=state,
            run_count=run_count,
            ground_truth_opened=ground_truth_opened,
            rerun_allowed=rerun_allowed,
        ))
    return tuple(records)
