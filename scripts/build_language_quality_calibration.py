from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
import zipfile

from acfv.clips.refinement import (
    FinalTranscriptRequest, SourceCorrection, SourceCorrectionState,
    _build_quality_report, classify_broken_sentence,
)
from acfv.clips.subtitles import (
    SubtitleWord, cluster_language_issues, language_release_state, translation_semantic_guard,
)


EXPECTED = {"clips": 12, "words": 1184, "low_confidence": 22,
            "local_redecodes": 29, "entities": 25, "broken_suspects": 30}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w']+", text.casefold())


def _creator(clip_id: str) -> str:
    return clip_id.split("-", 1)[0]


def _content_type(value: str) -> str:
    return "Simulation" if value == "Simulation/Other" else value


def _old_broken_suspect(text: str) -> bool:
    abrupt = re.compile(
        r"^(?:and|but|because|so|that|there's|i|you)\b|\b(?:and|but|because|so|that|i|you)$", re.I
    )
    return bool(text and (abrupt.search(text) or re.search(r"[!?.,]{3,}", text)))


def _context_sets(context: dict, sources: list[str], words: list[dict]) -> dict:
    creator = str(context.get("creator") or "")
    game = str(context.get("game") or "")
    ocr = str(context.get("ocr") or "")
    glossary = dict(context.get("glossary") or {})
    counts = Counter(
        str(word.get("text") or "").strip(".,!?;:\"'") for word in words
        if word.get("confidence") is not None and float(word["confidence"]) >= .80
        and re.fullmatch(r"[A-Z][A-Za-z0-9_-]{1,}", str(word.get("text") or "").strip(".,!?;:\"'"))
    )
    return {
        "glossary": glossary,
        "known_creator_entities": [creator] if creator else [],
        "game_terms": re.findall(r"\b[A-Z][A-Za-z0-9_-]{1,}\b", game),
        "ocr_entities": re.findall(r"\b[A-Z][A-Za-z0-9_-]{1,}\b", ocr),
        "repeated_high_confidence_entities": [token for token, count in counts.items() if count >= 2],
    }


def _segment_for_word(segments: list[dict], word: dict) -> dict:
    return next((row for row in segments
                 if round(float(row.get("end", 0)) * 1000) > int(word["start_ms"])
                 and round(float(row.get("start", 0)) * 1000) < int(word["end_ms"])), {})


def _overlapping_redecodes(rows: list[dict], start: int, end: int) -> list[dict]:
    return [row for row in rows if int(row.get("end_ms", 0)) > start and int(row.get("start_ms", 0)) < end]


def _word_decision(word: dict, redecode: list[dict], counts: Counter, context: dict) -> tuple[str, str]:
    token = re.sub(r"\W+", "", str(word.get("text") or "").casefold())
    exact_acoustic = any(token and token in _tokens(str(row.get("text") or "")) for row in redecode)
    repeated = counts[token] >= 3
    glossary = token in {str(k).casefold() for k in (context.get("glossary") or {})}
    critical = token in {"not", "no", "never", "can't", "cannot", "won't", "didn't"} or bool(
        re.fullmatch(r"\d+(?:\.\d+)?%?", token)
    )
    if critical and not (exact_acoustic and (repeated or glossary)):
        return "NEEDS_REVIEW", "critical semantic token lacks two independent evidence classes"
    if exact_acoustic or repeated:
        return "UNCHANGED_CONFIDENT", "independent acoustic agreement or repeated high-confidence usage supports raw"
    return "UNCHANGED_UNCERTAIN", "raw preserved; no independent evidence supports replacement"


def _mutation_summary() -> dict:
    critical = [
        ("I didn't scream.", "我尖叫了。", {}), ("I never won.", "我赢了。", {}),
        ("No one left.", "所有人都离开了。", {}), ("I can't move.", "我能动。", {}),
        ("Use 25%.", "使用20%。", {}), ("Three players.", "有2个玩家。", {}),
        ("Wait 10 seconds.", "等5秒。", {}),
        ("Saruei arrived.", "安妮来了。", {"known_creator_entities": ["Saruei"]}),
        ("Choose Mercy.", "选择安娜。", {"game_terms": ["Mercy"]}),
        ("This is the payoff.", "", {}),
    ]
    warning = [
        ("Are you ready?", "准备好了。", {}), ("This is fucking hard.", "这很难。", {}),
        ("Damn, okay.", "好吧。", {}), ("This is fine.", "笑死，这很好。", {}),
        ("Hello Bob.", "你好。", {}), ("Meet Alice.", "见面吧。", {}),
        ("Use Widget.", "使用组件。", {}), ("Okay Charlie.", "好的。", {}),
        ("Is Delta here?", "德尔塔在这里。", {}), ("Try Foobar.", "试试。", {}),
    ]
    harmless = [
        ("Guys, let's go.", "各位，我们走。", {}), ("Guys, let's go.", "兄弟们，我们走。", {}),
        ("Damn.", "靠。", {}), ("No!", "不！", {}),
        ("I didn't scream.", "我没有尖叫。", {}), ("Use 25%.", "使用25%。", {}),
        ("CS2", "CS2", {}), ("FMS", "FMS", {}),
        ("Twitch", "Twitch", {}), ("Saruei", "Saruei", {}),
    ]
    rows = []
    for expected, cases in (("CRITICAL", critical), ("WARNING", warning), ("HARMLESS", harmless)):
        for index, (source, target, kwargs) in enumerate(cases, 1):
            findings = translation_semantic_guard(source, target, semantic_position="PAYOFF", **kwargs)
            is_critical = any(item.get("critical") or item.get("hard_blocker") for item in findings)
            actual = "CRITICAL" if is_critical else "WARNING" if findings else "HARMLESS"
            rows.append({"case_id": f"{expected.lower()}-{index:02d}", "expected": expected,
                         "actual": actual, "source": source, "translation": target,
                         "findings": findings})
    return {
        "cases": rows, "total": len(rows),
        "critical_recall": sum(r["actual"] == "CRITICAL" for r in rows if r["expected"] == "CRITICAL") / 10,
        "warning_noncritical": sum(r["actual"] != "CRITICAL" for r in rows if r["expected"] == "WARNING") / 10,
        "harmless_false_critical": sum(r["actual"] == "CRITICAL" for r in rows if r["expected"] == "HARMLESS"),
    }


def build(source_root: Path, evidence_root: Path) -> dict:
    review_root = source_root / "final-language-review"
    clip_dirs = sorted(path.parent for path in review_root.glob("*/manifest.json"))
    root_cause, low_set, redecode_set, entity_set, risk_clips = [], [], [], [], []
    broken_rows = []
    totals = Counter()
    after = Counter()
    type_matrix: dict[str, Counter] = {}

    for clip_dir in clip_dirs:
        clip_id = clip_dir.name
        manifest = _read(clip_dir / "manifest.json")
        event = _read(clip_dir / "final_event_transcript.json")
        quality = _read(clip_dir / "final_transcript_quality.json")
        language = _read(clip_dir / "final_language_quality.json")
        track = _read(clip_dir / "bilingual_track.json")
        context = dict(manifest.get("translation_context") or {})
        content_type = _content_type(str(context.get("content_type") or "Unknown"))
        matrix = type_matrix.setdefault(content_type, Counter())
        words = list(event.get("aligned_words") or [])
        segments = list(event.get("raw_final_asr_segments") or [])
        redecodes = list(event.get("local_redecode_evidence") or [])
        cues = list(track.get("cues") or [])
        old_findings = [finding for cue in cues for finding in cue.get("semantic_guard_failures") or []]
        old_entities = [item for item in old_findings if item.get("code") == "ENTITY_MISMATCH"]
        old_broken = []
        for word in words:
            if "BROKEN_SENTENCE" in (word.get("quality_flags") or []):
                segment = _segment_for_word(segments, word)
                old_broken.append({"word": word, "segment": segment})
        trigger_rules = []
        if str(event.get("correction", {}).get("state")) == "NEEDS_REVIEW":
            trigger_rules.append("source_correction.state == NEEDS_REVIEW")
        if float(quality.get("low_confidence_word_ratio") or 0) > .10:
            trigger_rules.append("low_confidence_word_ratio > 0.10")
        if int(quality.get("broken_sentences") or 0) >= 2:
            trigger_rules.append("broken_sentences >= 2")
        if quality.get("payoff_low_confidence"):
            trigger_rules.append("payoff_low_confidence")
        if int(language.get("critical_semantic_guard_failures") or 0):
            trigger_rules.append("critical_semantic_guard_failures > 0")
        if language.get("Translation") == "NEEDS_REVIEW":
            trigger_rules.append("translation_release_state == NEEDS_REVIEW")
        if language.get("ASR") == "NEEDS_REVIEW":
            trigger_rules.append("asr_release_state == NEEDS_REVIEW")
        root_cause.append({
            "clip_id": clip_id, "creator": context.get("creator") or _creator(clip_id),
            "content_type": content_type, "duration_ms": manifest.get("duration_ms"),
            "word_count": len(words),
            "low_confidence_words": sum("LOW_WORD_CONFIDENCE" in (word.get("quality_flags") or []) for word in words),
            "local_redecode_count": len(redecodes), "broken_sentence_flags": len(old_broken),
            "entity_findings": len(old_entities),
            "negation_findings": sum(item.get("code") == "NEGATION_MISMATCH" for item in old_findings),
            "number_findings": sum(item.get("code") == "NUMBER_MISMATCH" for item in old_findings),
            "profanity_findings": sum(item.get("code") == "PROFANITY_STRENGTH_MISMATCH" for item in old_findings),
            "source_copy_findings": sum(item.get("code") == "UNEXPECTED_SOURCE_COPY" for item in old_findings),
            "current_asr_state": language.get("ASR"), "current_translation_state": language.get("Translation"),
            "current_overall_state": language.get("Overall"), "triggering_rules": trigger_rules,
        })

        token_counts = Counter(re.sub(r"\W+", "", str(word.get("text") or "").casefold()) for word in words
                               if "LOW_WORD_CONFIDENCE" not in (word.get("quality_flags") or []))
        for index, word in enumerate(words):
            if "LOW_WORD_CONFIDENCE" not in (word.get("quality_flags") or []):
                continue
            segment = _segment_for_word(segments, word)
            local = _overlapping_redecodes(redecodes, int(word["start_ms"]), int(word["end_ms"]))
            decision, reason = _word_decision(word, local, token_counts, context)
            low_set.append({
                "recording_id": manifest.get("event_id"), "clip_id": clip_id,
                "timestamp": int(word["start_ms"]), "raw_library_ASR": event.get("raw_library_transcript"),
                "final_large_v3_ASR": event.get("raw_final_asr"),
                "local_redecode_result": [row.get("text") for row in local],
                "previous_words": [item.get("text") for item in words[max(0, index - 3):index]],
                "current_word": word.get("text"),
                "next_words": [item.get("text") for item in words[index + 1:index + 4]],
                "word_confidence": word.get("confidence"), "avg_logprob": segment.get("avg_logprob"),
                "source_language": word.get("language") or track.get("source_language"),
                "glossary_match": re.sub(r"\W+", "", str(word.get("text") or "").casefold()) in {
                    str(key).casefold() for key in (context.get("glossary") or {})
                },
                "repeated_occurrence_elsewhere": token_counts[re.sub(r"\W+", "", str(word.get("text") or "").casefold())],
                "OCR_evidence": context.get("ocr") or "", "event_context": context,
                "current_quality_flags": word.get("quality_flags") or [],
                "old_decision": "NEEDS_REVIEW", "new_decision": decision,
                "evidence": {"local_redecode": bool(local), "high_confidence_repetition_count": token_counts[
                    re.sub(r"\W+", "", str(word.get("text") or "").casefold())]},
                "risk": "CRITICAL" if decision == "NEEDS_REVIEW" else "LOW",
                "reason": reason,
            })
            after[decision] += 1

        for index, row in enumerate(redecodes, 1):
            original_segment = next((segment for segment in segments
                                     if round(float(segment.get("end", 0)) * 1000) > int(row.get("start_ms", 0))
                                     and round(float(segment.get("start", 0)) * 1000) < int(row.get("end_ms", 0))), {})
            original = str(original_segment.get("text") or "").strip()
            local_text = str(row.get("text") or "").strip()
            original_tokens, local_tokens = set(_tokens(original)), set(_tokens(local_text))
            agreement = len(original_tokens & local_tokens) / max(len(original_tokens | local_tokens), 1)
            redecode_set.append({
                "clip_id": clip_id, "redecode_id": f"{clip_id}:{index:02d}",
                "timestamp": int(row.get("start_ms", 0)), "pass_A_original_final_ASR": original,
                "pass_B_local_redecode": local_text, "consistent": original.casefold() == local_text.casefold(),
                "changed_words": sorted(original_tokens ^ local_tokens), "confidence_delta": None,
                "confidence_delta_reason": "historical local decode did not persist probability/logprob",
                "context_agreement": round(agreement, 4),
                "glossary_agreement": any(str(term).casefold() in local_text.casefold()
                                           for term in (context.get("glossary") or {})),
                "same_phrase_evidence": local_text.casefold() in str(event.get("raw_final_asr") or "").casefold()
                                        if local_text else False,
                "decision": "SUPPORTS_RAW" if agreement >= .75 else "INCONCLUSIVE",
            })

        sets = _context_sets(context, [str(cue.get("source_text") or "") for cue in cues], words)
        new_translation_issues = []
        for cue in cues:
            new_translation_issues.extend(translation_semantic_guard(
                str(cue.get("source_text") or ""), str(cue.get("zh_text") or ""),
                semantic_position="CONTEXT", clip_id=clip_id,
                cue_id=str(cue.get("cue_id") or ""),
                start_ms=int(cue.get("start_ms") or 0), end_ms=int(cue.get("end_ms") or 0),
                **sets,
            ))
        for item in old_entities:
            token = str(item.get("detail") or "")
            new = next((row for row in new_translation_issues
                        if row.get("code") == "ENTITY_MISMATCH" and row.get("detail") == token), None)
            entity_set.append({
                "clip_id": clip_id, "source_token": token, "translated_token": None,
                "context": context, "current_entity_type": "CAPITALIZATION_HEURISTIC",
                "actual_evidence_source": (new or {}).get("evidence", {}).get("entity_type", "NONE"),
                "current_severity": "CRITICAL", "only_capitalized": not bool(new and new.get("critical")),
                "glossary_backed": token.casefold() in {str(k).casefold() for k in sets["glossary"]},
                "OCR_backed": token.casefold() in {str(v).casefold() for v in sets["ocr_entities"]},
                "repeated": token in sets["repeated_high_confidence_entities"],
                "known_creator_or_game_entity": token.casefold() in {
                    str(v).casefold() for v in sets["known_creator_entities"] + sets["game_terms"]
                },
                "before_type": "CAPITALIZATION_HEURISTIC", "after_type": (
                    (new or {}).get("evidence", {}).get("entity_type", "NOT_AN_ENTITY")
                ), "before_severity": "CRITICAL", "after_severity": (new or {}).get("severity", "NONE"),
                "reason": "capitalization alone downgraded" if not new or not new.get("critical")
                          else "independent entity evidence retained",
            })

        for suspect in old_broken:
            segment = suspect["segment"]
            broken_rows.append({"clip_id": clip_id, "timestamp": suspect["word"].get("start_ms"),
                                "text": segment.get("text"),
                                "classification": classify_broken_sentence(str(segment.get("text") or "")).value})

        archived_correction = event.get("correction") or {}
        correction_state = (SourceCorrectionState.UNCHANGED_UNCERTAIN.value
                            if archived_correction.get("needs_review_reasons") == ["EMPTY_CORRECTION"]
                            else str(archived_correction.get("state") or SourceCorrectionState.UNCHANGED_CONFIDENT.value))
        correction = SourceCorrection(
            str(archived_correction.get("raw_text") or event.get("raw_final_asr") or ""),
            str(event.get("raw_final_asr") or ""), confidence=float(archived_correction.get("confidence") or 0),
            reason="raw_preserved_after_calibration", state=correction_state,
            needs_review_reasons=tuple(archived_correction.get("needs_review_reasons") or ()),
        )
        request = FinalTranscriptRequest(
            recording_id=str(manifest.get("event_id") or clip_id), event_id=str(manifest.get("event_id") or clip_id),
            source_path=str(manifest.get("clean_path") or "historical"),
            source_duration_ms=max(int(event.get("context_end_ms") or 0), int(event.get("event_end_ms") or 0)),
            event_start_ms=int(event.get("event_start_ms") or 0), event_end_ms=int(event.get("event_end_ms") or 0),
            source_language=str(track.get("source_language") or "en"),
            payoff_anchor_ms=manifest.get("payoff_anchor_ms"),
        )
        calibrated = _build_quality_report(
            [SubtitleWord(**word) for word in words], correction=correction, request=request,
            local_redecode_count=len(redecodes),
        )
        translation_state, _, _ = language_release_state(new_translation_issues)
        combined = list(calibrated.issues) + new_translation_issues
        overall, total_risk, max_risk = language_release_state(combined, timeline_valid=language.get("Timeline") == "READY")
        clusters = cluster_language_issues(combined, clip_id=clip_id)
        risk_clips.append({
            "clip_id": clip_id, "creator": context.get("creator"), "content_type": content_type,
            "issues": combined, "risk_score": total_risk, "maximum_issue_risk": max_risk,
            "raw_finding_count": len(combined), "cluster_count": len(clusters),
            "clusters": [cluster.to_dict() for cluster in clusters],
            "ASR": calibrated.final_quality_state, "Translation": translation_state,
            "Timeline": language.get("Timeline"), "Overall": overall,
            "critical_issues": [row for row in combined if row.get("hard_blocker") or row.get("critical")],
            "warnings": [row for row in combined if row.get("severity") in {"WARNING", "HIGH"}
                         and not row.get("hard_blocker")],
        })
        matrix["clips"] += 1
        matrix["low_confidence"] += int(quality.get("low_confidence_words") or 0)
        matrix["auto_corrections"] += sum(row["new_decision"] == "AUTO_CORRECTED" for row in low_set
                                           if row["clip_id"] == clip_id)
        matrix["warnings"] += len(risk_clips[-1]["warnings"])
        matrix["critical"] += len(risk_clips[-1]["critical_issues"])
        matrix[overall] += 1
        totals.update({"clips": 1, "words": len(words),
                       "low_confidence": int(quality.get("low_confidence_words") or 0),
                       "local_redecodes": len(redecodes), "entities": len(old_entities),
                       "broken_suspects": len(old_broken)})

    actual = {key: totals[key] for key in EXPECTED}
    if actual != EXPECTED:
        raise RuntimeError(f"Fixed-set drift: expected {EXPECTED}, got {actual}")
    mutation = _mutation_summary()
    if mutation["critical_recall"] != 1.0 or mutation["harmless_false_critical"] != 0:
        raise RuntimeError(f"Mutation acceptance failed: {mutation}")

    root_payload = {"schema_version": "1.0", "baseline_commit": "ae63f6f7f80e363f15f49fb78b871d9ea028455a",
                    "recovered_snapshot_commit": "753add2", "fixed_set": actual, "clips": root_cause}
    _write(evidence_root / "language-quality-calibration-root-cause.json", root_payload)
    _write(evidence_root / "low-confidence-word-fixed-set.json", {"count": len(low_set), "items": low_set})
    _write(evidence_root / "local-redecode-fixed-set.json", {"count": len(redecode_set), "items": redecode_set})
    _write(evidence_root / "entity-guard-fixed-set.json", {"count": len(entity_set), "items": entity_set})
    release_counts = Counter(row["Overall"] for row in risk_clips)
    broken_counts = Counter(row["classification"] for row in broken_rows)
    risk_payload = {
        "schema_version": "1.0", "clips": risk_clips, "release_counts": dict(release_counts),
        "correction_decisions": dict(after), "broken_sentence_classification": dict(broken_counts),
        "broken_sentence_items": broken_rows, "content_type_matrix": {key: dict(value) for key, value in type_matrix.items()},
        "mutation_suite": mutation,
    }
    _write(evidence_root / "language-risk-report.json", risk_payload)
    after_entity_critical = sum(item["after_severity"] == "CRITICAL" for item in entity_set)
    after_broken = broken_counts["TRUE_BROKEN"] + broken_counts["ASR_ERROR"]
    after_critical_translation = sum(len(row["critical_issues"]) for row in risk_clips)
    comparison = [
        "# Language Quality Calibration Comparison", "", "| Metric | Before | After | Delta |",
        "|---|---:|---:|---:|",
        f"| Low-confidence words | 22 | 22 | 0 |",
        f"| AUTO_CORRECTED | 0 | {after['AUTO_CORRECTED']} | {after['AUTO_CORRECTED']} |",
        f"| Entity findings | 25 | {sum(item['after_severity'] != 'NONE' for item in entity_set)} | {sum(item['after_severity'] != 'NONE' for item in entity_set) - 25} |",
        f"| Critical entity findings | 25 | {after_entity_critical} | {after_entity_critical - 25} |",
        f"| Broken-sentence findings | 30 | {after_broken} | {after_broken - 30} |",
        f"| Critical translation findings | 29 | {after_critical_translation} | {after_critical_translation - 29} |",
        f"| READY | 0 | {release_counts['READY']} | {release_counts['READY']} |",
        f"| READY_WITH_WARNINGS | 0 | {release_counts['READY_WITH_WARNINGS']} | {release_counts['READY_WITH_WARNINGS']} |",
        f"| NEEDS_REVIEW | 12 | {release_counts['NEEDS_REVIEW']} | {release_counts['NEEDS_REVIEW'] - 12} |",
        "| Correction median runtime | 16.606s | 16.606s (no new model call) | 0% |",
        "| Total language median runtime | 79.361s | 79.361s + deterministic guards | <1% estimated |",
        "", "The after pass reuses the same 12 archived artifacts. It does not claim new acoustic decoding.",
    ]
    (evidence_root / "language-quality-calibration-comparison.md").write_text("\n".join(comparison) + "\n", encoding="utf-8")
    return {"fixed_set": actual, "release_counts": dict(release_counts), "mutation": mutation,
            "correction_decisions": dict(after), "broken": dict(broken_counts),
            "entity_after_critical": after_entity_critical, "risk_clips": risk_clips}


def build_review_pack(source_root: Path, risk: dict, output: Path) -> dict:
    staging = output.parent / "language-quality-calibration-review-pack"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    clips = risk["risk_clips"]
    for clip in clips:
        clip_id = clip["clip_id"]
        source = source_root / "final-language-review" / clip_id
        asr_source = source_root / "asr" / "asr-v2" / clip_id
        target = staging / clip_id
        target.mkdir()
        for name in ("final_event_transcript.json", "final_transcript_quality.json", "bilingual_track.json"):
            shutil.copy2(source / name, target / name)
        shutil.copy2(asr_source / "audio.wav", target / "original_source_audio.wav")
        (target / "calibrated-review.json").write_text(
            json.dumps(clip, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        media = source / "FINAL_STANDARD.mp4"
        proxy = target / "final_bilingual_proxy.mp4"
        command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(media),
                   "-vf", "scale=-2:480", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
                   "-c:a", "aac", "-b:a", "64k", str(proxy)]
        subprocess.run(command, check=True, timeout=600)
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(staging))
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    size = output.stat().st_size
    if size > 300 * 1024 * 1024:
        raise RuntimeError(f"Review pack exceeds 300 MiB: {size}")
    return {"path": str(output.resolve()), "size_bytes": size, "sha256": digest,
            "clips": len(clips), "issues": sum(len(item["issues"]) for item in clips)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the frozen language-quality calibration evidence.")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, default=Path("evidence/validation"))
    parser.add_argument("--review-pack", type=Path)
    args = parser.parse_args()
    started = time.perf_counter()
    result = build(args.source_root, args.evidence_root)
    if args.review_pack:
        result["review_pack"] = build_review_pack(args.source_root, result, args.review_pack)
    result["wall_time_seconds"] = round(time.perf_counter() - started, 3)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
