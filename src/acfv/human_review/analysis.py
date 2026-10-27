from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from .repository import HumanReviewRepository


def _tokens(text: str) -> list[str]:
    return [token for token in text.lower().strip().split() if token]


def edit_distance(left: list[str], right: list[str]) -> int:
    row = list(range(len(right) + 1))
    for index, a in enumerate(left, 1):
        next_row = [index]
        for offset, b in enumerate(right, 1):
            next_row.append(min(next_row[-1] + 1, row[offset] + 1, row[offset - 1] + (a != b)))
        row = next_row
    return row[-1]


def error_rate(reference: str, hypothesis: str, *, characters: bool = False) -> float | None:
    ref = list(reference.replace(" ", "")) if characters else _tokens(reference)
    hyp = list(hypothesis.replace(" ", "")) if characters else _tokens(hypothesis)
    if not ref:
        return None
    return edit_distance(ref, hyp) / len(ref)


def _distribution(rows: Iterable[dict[str, Any]], key: str) -> dict[str, int]:
    values = (str(row.get("answer", {}).get(key, "")) for row in rows if row.get("status") == "completed")
    return dict(Counter(value for value in values if value))


def _average_detail(rows: Iterable[dict[str, Any]], key: str) -> float | None:
    values: list[float] = []
    for row in rows:
        value = row.get("answer", {}).get("details", {}).get(key)
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return sum(values) / len(values) if values else None


def _blind_wins(rows: Iterable[dict[str, Any]], a_key: str, b_key: str) -> dict[str, int]:
    wins: Counter[str] = Counter()
    for row in rows:
        choice = row.get("answer", {}).get("choice")
        private = row.get("private", {})
        if choice == "a" and private.get(a_key):
            wins[str(private[a_key])] += 1
        elif choice == "b" and private.get(b_key):
            wins[str(private[b_key])] += 1
        elif choice in ("same", "both_bad", "both_wrong"):
            wins[str(choice)] += 1
    return dict(wins)


class HumanReviewAnalysis:
    def __init__(self, repository: HumanReviewRepository) -> None:
        self.repository = repository

    @staticmethod
    def maturity(count: int, useful: int = 100) -> str:
        if count < 30:
            return "Not enough data"
        if count < useful:
            return "Preliminary"
        return "Useful estimate"

    def calculate(self) -> dict[str, Any]:
        rows = self.repository.annotation_rows()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(str(row["task"]), []).append(row)
        result: dict[str, Any] = {}
        asr = grouped.get("asr", [])
        wers: list[float] = []
        cers: list[float] = []
        for row in asr:
            answer = row["answer"]
            reference = str(answer.get("human_transcript", "")).strip()
            hypothesis = str(answer.get("current_asr", "")).strip()
            if reference and hypothesis:
                wer = error_rate(reference, hypothesis)
                cer = error_rate(reference, hypothesis, characters=True)
                if wer is not None: wers.append(wer)
                if cer is not None: cers.append(cer)
        result["asr"] = {
            "reviewed": len(asr),
            "maturity": self.maturity(len(asr)),
            "labels": _distribution(asr, "choice"),
            "wer": sum(wers) / len(wers) if wers else None,
            "cer": sum(cers) / len(cers) if cers else None,
            "confidence_accuracy": self._confidence_accuracy(asr),
        }
        identity = grouped.get("identity", [])
        identity_completed = [row for row in identity if row.get("status") == "completed"]
        result["identity"] = {
            "reviewed": len(identity), "maturity": self.maturity(len(identity)),
            "labels": _distribution(identity, "choice"),
            "accuracy": (
                sum(row.get("answer", {}).get("choice") == "correct" for row in identity_completed) / len(identity_completed)
                if identity_completed else None
            ),
        }
        trusted = grouped.get("trusted_speech", [])
        result["trusted_speech"] = {
            "reviewed": len(trusted), "maturity": self.maturity(len(trusted)),
            "speaker": _distribution(trusted, "speaker"),
            "transcript": _distribution(trusted, "transcript"),
            "both_correct": sum(
                row.get("answer", {}).get("speaker") == "correct" and row.get("answer", {}).get("transcript") == "correct"
                for row in trusted
            ),
        }
        adaptive = grouped.get("adaptive_asr", [])
        adaptive_generic_wer: list[float] = []
        adaptive_candidate_wer: list[float] = []
        adaptive_generic_cer: list[float] = []
        adaptive_candidate_cer: list[float] = []
        for row in adaptive:
            truth = str(row.get("answer", {}).get("human_transcript", "")).strip()
            if not truth:
                continue
            prompt = row.get("prompt", {})
            private = row.get("private", {})
            generic = str(prompt.get("a" if private.get("strategy_a") == "generic" else "b", ""))
            candidate = str(prompt.get("a" if private.get("strategy_a") == "adaptive" else "b", ""))
            for target, text, characters in (
                (adaptive_generic_wer, generic, False), (adaptive_candidate_wer, candidate, False),
                (adaptive_generic_cer, generic, True), (adaptive_candidate_cer, candidate, True),
            ):
                rate = error_rate(truth, text, characters=characters)
                if rate is not None:
                    target.append(rate)
        result["adaptive_asr"] = {
            "reviewed": len(adaptive), "maturity": self.maturity(len(adaptive)),
            "blind_wins": _blind_wins(adaptive, "strategy_a", "strategy_b"),
            "ground_truth_samples": len(adaptive_generic_wer),
            "generic_wer": sum(adaptive_generic_wer) / len(adaptive_generic_wer) if adaptive_generic_wer else None,
            "adaptive_wer": sum(adaptive_candidate_wer) / len(adaptive_candidate_wer) if adaptive_candidate_wer else None,
            "generic_cer": sum(adaptive_generic_cer) / len(adaptive_generic_cer) if adaptive_generic_cer else None,
            "adaptive_cer": sum(adaptive_candidate_cer) / len(adaptive_candidate_cer) if adaptive_candidate_cer else None,
        }
        for task, key in (
            ("translation", "choice"),
            ("watchability", "choice"),
            ("subtitle", "choice"),
            ("publishability", "choice"),
        ):
            task_rows = grouped.get(task, [])
            result[task] = {
                "reviewed": len(task_rows),
                "maturity": self.maturity(len(task_rows)),
                "labels": _distribution(task_rows, key),
            }
        translation = grouped.get("translation", [])
        result["translation"].update({
            "provider_wins": _blind_wins(translation, "provider_a", "provider_b"),
            "ratings": {key: _average_detail(translation, key) for key in ("accuracy", "naturalness", "tone")},
        })
        watchability = grouped.get("watchability", [])
        result["watchability"].update({
            "strategy_wins": _blind_wins(watchability, "strategy_a", "strategy_b"),
            "reasons": dict(Counter(
                key for row in watchability
                for key, enabled in row.get("answer", {}).get("details", {}).items()
                if enabled is True
            )),
            "by_content_type": {
                content_type: _distribution((row for row in watchability if row.get("content_type") == content_type), "choice")
                for content_type in sorted({str(row.get("content_type")) for row in watchability if row.get("content_type")})
            },
        })
        subtitle = grouped.get("subtitle", [])
        result["subtitle"]["by_mode"] = {
            mode: _distribution((row for row in subtitle if row.get("prompt", {}).get("mode") == mode), "choice")
            for mode in ("cue", "clip")
        }
        result["subtitle"]["cps_readability"] = self._cps_readability(subtitle)
        boundary = grouped.get("boundary", [])
        result["boundary"] = {
            "reviewed": len(boundary),
            "maturity": self.maturity(len(boundary)),
            "start": _distribution(boundary, "start"),
            "end": _distribution(boundary, "end"),
            "length": _distribution(boundary, "length"),
            "preferred_profile": dict(Counter(
                str(row["answer"].get("details", {}).get("preferred_profile"))
                for row in boundary
                if row["answer"].get("details", {}).get("preferred_profile")
            )),
        }
        rejects = Counter()
        for row in grouped.get("publishability", []):
            for reason in row["answer"].get("reject_reasons", []):
                rejects[str(reason)] += 1
        result["publishability"]["reject_reasons"] = dict(rejects)
        result["publishability"]["ratings"] = {
            key: _average_detail(grouped.get("publishability", []), f"rating_{key}")
            for key in ("content", "pacing", "asr", "translation", "subtitle")
        }
        return result

    @staticmethod
    def _confidence_accuracy(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
        buckets: dict[str, list[bool]] = {"low": [], "medium": [], "high": []}
        for row in rows:
            try:
                confidence = float(row.get("private", {}).get("confidence"))
            except (TypeError, ValueError):
                continue
            bucket = "low" if confidence < 0.4 else "medium" if confidence < 0.75 else "high"
            buckets[bucket].append(row.get("answer", {}).get("choice") == "correct")
        return {
            key: {"samples": len(values), "correct_rate": sum(values) / len(values)}
            for key, values in buckets.items() if values
        }

    @staticmethod
    def _cps_readability(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
        buckets: dict[str, list[bool]] = {"comfortable": [], "borderline": [], "fast": []}
        for row in rows:
            try:
                cps = float(row.get("private", {}).get("cps"))
            except (TypeError, ValueError):
                continue
            bucket = "comfortable" if cps <= 15 else "borderline" if cps <= 20 else "fast"
            buckets[bucket].append(row.get("answer", {}).get("choice") == "good")
        return {
            key: {"samples": len(values), "good_rate": sum(values) / len(values)}
            for key, values in buckets.items() if values
        }
