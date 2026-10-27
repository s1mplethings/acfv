from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable
from statistics import median, pstdev


class DurationProfile(str, Enum):
    SHORT = "SHORT"
    STANDARD = "STANDARD"
    LONG = "LONG"
    FULL_EVENT = "FULL_EVENT"
    CUSTOM = "CUSTOM"


class VariantStatus(str, Enum):
    READY = "READY"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    DURATION_CONFLICT = "DURATION_CONFLICT"
    INCOMPLETE_SENTENCE_BOUNDARY = "INCOMPLETE_SENTENCE_BOUNDARY"


@dataclass(frozen=True)
class SemanticBoundaryUnit:
    start_ms: int
    end_ms: int
    text: str
    roles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValueError("Semantic boundary units require positive monotonic timing")


@dataclass(frozen=True)
class DurationRequest:
    profile: DurationProfile
    target_seconds: float | None = None
    min_seconds: float | None = None
    max_seconds: float | None = None
    required_evidence_span_ms: tuple[int, int] | None = None


@dataclass(frozen=True)
class DurationVariant:
    profile: DurationProfile
    status: VariantStatus
    start_ms: int
    end_ms: int
    event_id: str
    payoff_anchor_ms: int
    extension_reason: str = ""

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


_PROFILE_RANGES = {
    DurationProfile.SHORT: (20_000, 32_500, 60_000),
    DurationProfile.STANDARD: (45_000, 67_500, 120_000),
    DurationProfile.LONG: (90_000, 135_000, 240_000),
}


class DurationProfileService:
    """Select content-first boundaries around evidence and a payoff anchor.

    Profile duration is deliberately a small tie-breaker. Missing evidence,
    missing setup/payoff, a word cut, or unrelated padding must always cost
    more than being away from a nominal profile target.
    """

    def generate(
        self,
        *,
        event_id: str,
        units: Iterable[SemanticBoundaryUnit],
        payoff_anchor_ms: int,
        source_duration_ms: int,
        request: DurationRequest,
    ) -> DurationVariant:
        ordered = sorted(units, key=lambda item: (item.start_ms, item.end_ms))
        if not ordered or not any(item.start_ms <= payoff_anchor_ms <= item.end_ms for item in ordered):
            raise ValueError("The event payoff anchor must be covered by a semantic unit")
        if request.profile is DurationProfile.FULL_EVENT:
            duration = ordered[-1].end_ms - ordered[0].start_ms
            status = VariantStatus.READY if 15_000 <= duration <= 300_000 else VariantStatus.NOT_AVAILABLE
            reason = "natural_event_boundaries" if status is VariantStatus.READY else "full_event_outside_15_to_300s_safety_range"
            return self._finish(event_id, payoff_anchor_ms, ordered[0].start_ms, ordered[-1].end_ms,
                                source_duration_ms, request.profile, reason, status=status)

        minimum, target, maximum = self._limits(request)
        required = request.required_evidence_span_ms
        if required is not None:
            required = (min(required), max(required))
            if required[0] < 0 or required[1] <= required[0]:
                raise ValueError("Required evidence span must be positive and ordered")
        candidates: list[dict[str, object]] = []
        for left in range(len(ordered)):
            roles: set[str] = set()
            for right in range(left, len(ordered)):
                unit = ordered[right]
                roles.update(role.casefold() for role in unit.roles)
                start, end = ordered[left].start_ms, unit.end_ms
                final_unit = right == len(ordered) - 1
                sentence_complete = bool(re.search(r"[.!?。！？][\"'”’)]?$", unit.text.strip()))
                pause_complete = (
                    not final_unit and ordered[right + 1].start_ms - unit.end_ms >= 800
                )
                contains_anchor = start <= payoff_anchor_ms <= end
                contains_evidence = required is None or (start <= required[0] and end >= required[1])
                structurally_complete = {"setup", "payoff"} <= roles
                if contains_anchor and contains_evidence and structurally_complete:
                    previous_gap = ordered[left].start_ms - ordered[left - 1].end_ms if left else 10_000
                    starts_naturally = left == 0 or previous_gap >= 800 or bool(
                        re.search(r"[.!?。！？][\"'”’)]?$", ordered[left - 1].text.strip())
                    )
                    ends_naturally = final_unit or sentence_complete or pause_complete
                    if not ends_naturally:
                        continue
                    span_units = ordered[left:right + 1]
                    unrelated = sum(
                        1 for item in span_units
                        if "unrelated" in {role.casefold() for role in item.roles}
                    )
                    duration = end - start
                    # Duration can break a close tie, never overrule content.
                    duration_penalty = min(0.75, abs(duration - target) / max(target, 1) * 0.75)
                    aftermath = sum(
                        "aftermath" in {role.casefold() for role in item.roles}
                        for item in span_units
                    )
                    semantic_score = (
                        8.0 + 5.0
                        + (3.0 if sentence_complete else 0.0)
                        + (2.0 if pause_complete or final_unit else 0.0)
                        + (2.0 if starts_naturally else 0.0)
                        + min(2.0, aftermath * 0.5)
                        - unrelated * 4.0
                        - max(0, len(span_units) - 8) * 0.20
                        - duration_penalty
                    )
                    candidates.append({
                        "start": start, "end": end, "roles": set(roles),
                        "score": semantic_score, "duration_penalty": duration_penalty,
                        "aftermath": aftermath,
                    })
        if not candidates:
            return DurationVariant(request.profile, VariantStatus.NOT_AVAILABLE, 0, 0, event_id, payoff_anchor_ms,
                                   "required_evidence_setup_and_payoff_cannot_share_a_natural_window")

        # FULL_EVENT owns the complete natural range. Other profiles prefer a
        # proper semantic sub-window when one exists so variants remain useful.
        proper = [item for item in candidates if (item["start"], item["end"]) != (ordered[0].start_ms, ordered[-1].end_ms)]
        if proper:
            candidates = proper

        if request.profile is DurationProfile.SHORT:
            pool = [item for item in candidates if int(item["end"]) - int(item["start"]) <= maximum]
            if not pool:
                return DurationVariant(request.profile, VariantStatus.NOT_AVAILABLE, 0, 0, event_id,
                                       payoff_anchor_ms, "complete_event_does_not_fit_short")
        elif request.profile is DurationProfile.LONG:
            pool = [item for item in candidates if int(item["aftermath"]) > 0]
            if not pool:
                return DurationVariant(request.profile, VariantStatus.NOT_AVAILABLE, 0, 0, event_id,
                                       payoff_anchor_ms, "no_useful_setup_or_aftermath_for_long")
        else:
            pool = candidates
        if request.profile is DurationProfile.STANDARD:
            best_score = max(float(item["score"]) for item in pool)
            near_best = [item for item in pool if float(item["score"]) >= best_score - 0.5]
            chosen = min(near_best, key=lambda item: (
                int(item["end"]) - int(item["start"]), -float(item["score"])
            ))
        elif request.profile is DurationProfile.LONG:
            chosen = max(pool, key=lambda item: (
                float(item["score"]), int(item["end"]) - int(item["start"])
            ))
        elif request.profile is DurationProfile.SHORT:
            chosen = min(pool, key=lambda item: (
                int(item["end"]) - int(item["start"]), -float(item["score"])
            ))
        else:
            chosen = max(pool, key=lambda item: (
                float(item["score"]), -(int(item["end"]) - int(item["start"]))
            ))
        start, end = int(chosen["start"]), int(chosen["end"])
        duration = end - start
        status = VariantStatus.READY
        reason = "content_first_semantic_boundary"
        if request.profile is DurationProfile.CUSTOM and not (minimum <= duration <= maximum):
            status = VariantStatus.DURATION_CONFLICT
            reason = "content_first_natural_boundary_outside_custom_range"
        elif duration < 15_000:
            status = VariantStatus.NOT_AVAILABLE
            reason = "semantic_event_below_15s_viability_floor"
        elif duration < minimum:
            reason = "complete_event_shorter_than_profile_range"
        elif duration > target:
            reason = "complete_event_exceeds_nominal_target"
        if required is not None:
            reason += "+required_evidence_preserved"
        return self._finish(event_id, payoff_anchor_ms, start, end, source_duration_ms,
                            request.profile, reason, status=status)

    def generate_all(
        self,
        *,
        event_id: str,
        units: Iterable[SemanticBoundaryUnit],
        payoff_anchor_ms: int,
        source_duration_ms: int,
        required_evidence_span_ms: tuple[int, int] | None = None,
    ) -> list[DurationVariant]:
        material = list(units)
        variants = [
            self.generate(event_id=event_id, units=material, payoff_anchor_ms=payoff_anchor_ms,
                          source_duration_ms=source_duration_ms,
                          request=DurationRequest(profile, required_evidence_span_ms=required_evidence_span_ms))
            for profile in (DurationProfile.SHORT, DurationProfile.STANDARD, DurationProfile.LONG, DurationProfile.FULL_EVENT)
        ]
        # STANDARD is the canonical shortest complete event. If SHORT cannot
        # be meaningfully shorter, SHORT is unavailable; never suppress the
        # canonical STANDARD and then re-run ASR/translation to recover it.
        standard = variants[1]
        if standard.status is VariantStatus.READY:
            short = variants[0]
            if short.status is VariantStatus.READY and short.duration_ms >= standard.duration_ms:
                variants[0] = DurationVariant(
                    short.profile, VariantStatus.NOT_AVAILABLE, short.start_ms, short.end_ms,
                    short.event_id, short.payoff_anchor_ms, "profile_has_no_distinct_semantic_boundary",
                )
            long = variants[2]
            if long.status is VariantStatus.READY and long.duration_ms <= standard.duration_ms:
                variants[2] = DurationVariant(
                    long.profile, VariantStatus.NOT_AVAILABLE, long.start_ms, long.end_ms,
                    long.event_id, long.payoff_anchor_ms, "profile_has_no_distinct_semantic_boundary",
                )
        return variants

    @staticmethod
    def _limits(request: DurationRequest) -> tuple[int, int, int]:
        if request.profile is not DurationProfile.CUSTOM:
            return _PROFILE_RANGES[request.profile]
        if request.target_seconds is not None:
            target = int(request.target_seconds * 1000)
            if not 5_000 <= target <= 600_000:
                raise ValueError("Custom target must be between 5 and 600 seconds")
            return max(5_000, target - 5_000), target, min(600_000, target + 5_000)
        minimum = int((request.min_seconds or 5) * 1000)
        maximum = int((request.max_seconds or 600) * 1000)
        if minimum < 5_000 or maximum > 600_000 or maximum < minimum:
            raise ValueError("Custom range must be ordered and within 5 to 600 seconds")
        return minimum, (minimum + maximum) // 2, maximum

    @staticmethod
    def _finish(event_id: str, anchor: int, start: int, end: int, source_duration: int,
                profile: DurationProfile, reason: str, *, status: VariantStatus = VariantStatus.READY) -> DurationVariant:
        if start < 10_000 or source_duration - end < 20_000:
            if reason.startswith("semantic_event_below_15s_viability_floor"):
                reason = "event_shorter_than_profile_target_preserved+" + reason
            return DurationVariant(
                profile, VariantStatus.NOT_AVAILABLE, start, end, event_id, anchor,
                f"{reason}+SOURCE_EDGE",
            )
        return DurationVariant(profile, status, start, end, event_id, anchor, reason)


def duration_distribution(durations_ms: Iterable[int]) -> dict[str, float | int | bool | list[float]]:
    values = [int(value) for value in durations_ms if int(value) > 0]
    if not values:
        return {"count": 0, "min_seconds": 0, "median_seconds": 0, "max_seconds": 0,
                "stddev_seconds": 0, "unique_rounded_durations": [], "count_18_to_22_seconds": 0,
                "fail_fixed_duration_path": False, "auto_suspect_exact_duration": False}
    rounded = [round(value / 1000, 1) for value in values]
    counts = {value: rounded.count(value) for value in set(rounded)}
    concentration = max(counts.values()) / len(values)
    fixed_20 = sum(18_000 <= value <= 22_000 for value in values)
    return {
        "count": len(values), "min_seconds": min(values) / 1000,
        "median_seconds": median(values) / 1000, "max_seconds": max(values) / 1000,
        "stddev_seconds": pstdev(values) / 1000 if len(values) > 1 else 0,
        "unique_rounded_durations": sorted(set(rounded)), "count_18_to_22_seconds": fixed_20,
        "fail_fixed_duration_path": fixed_20 / len(values) > 0.75,
        "auto_suspect_exact_duration": concentration > 0.5,
    }


__all__ = ["DurationProfile", "DurationProfileService", "DurationRequest", "DurationVariant", "duration_distribution",
           "SemanticBoundaryUnit", "VariantStatus"]
