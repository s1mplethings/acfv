from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sqlite3
import time

from acfv.clips import ArgosTranslationProvider, QwenTranslationProvider, TranslationMode
from acfv.llm.openai_client import OpenAIClientConfig, OpenAIJsonClient


ROOT = Path(__file__).resolve().parents[1]
DATABASES = [
    ("core", ROOT / "var/intelligence_quality_20261008/library_v2.db"),
    ("q8", ROOT / "var/cross_library_generalization/q8-library.db"),
    ("holdout", ROOT / "var/cross_library_generalization/tpp-library-service.db"),
]
CATEGORIES = [
    "fear reaction", "profanity", "denial", "sarcasm", "joke", "repeated phrase",
    "game term", "creator slang", "chatting story", "collab response",
    "background music contamination", "normal sentence",
]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _cue_group(row: sqlite3.Row) -> list[dict[str, str]]:
    try:
        evidence = json.loads(row["evidence_json"] or "[]")
    except json.JSONDecodeError:
        evidence = []
    texts = [_clean(str(item.get("text") or "")) for item in evidence if item.get("type") == "transcript"]
    sentence_like: list[str] = []
    for text in texts:
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            words = sentence.split()
            sentence_like.extend(" ".join(words[index:index + 24]) for index in range(0, len(words), 24))
    texts = [text for text in sentence_like if text]
    if len(texts) < 2:
        base = _clean(row["transcript_text"] or row["summary"] or "")
        texts = [item.strip() for item in re.split(r"(?<=[.!?])\s+", base) if item.strip()]
    if not texts:
        texts = ["[no usable creator speech]"]
    return [{"cue_id": f"C{index + 1:02d}", "text": text} for index, text in enumerate(texts[:5])]


def _fixed_set() -> list[dict]:
    rows: list[dict] = []
    for label, database in DATABASES:
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        material = connection.execute(
            """SELECT m.id,m.creator_id,m.recording_id,m.summary,m.transcript_text,m.evidence_json,
                      r.title AS recording_title
                 FROM library_moments m JOIN library_recordings r ON r.id=m.recording_id
                WHERE m.status='FINAL' AND length(m.transcript_text)>=35
                ORDER BY m.recording_id,m.start_ms"""
        ).fetchall()
        connection.close()
        for row in material:
            cues = _cue_group(row)
            if cues and cues[0]["text"] != "[no usable creator speech]":
                rows.append({
                    "case_id": f"T{len(rows) + 1:02d}", "library": label,
                    "creator_id": row["creator_id"], "recording_id": row["recording_id"],
                    "recording_title": row["recording_title"], "event_summary": _clean(row["summary"]),
                    "category": CATEGORIES[len(rows) % len(CATEGORIES)], "cues": cues,
                })
            if len(rows) >= 40:
                return rows
    if len(rows) < 40:
        raise RuntimeError(f"Fixed set requires 40 real cue groups; found {len(rows)}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "var/final_clip_quality/translation")
    parser.add_argument("--restart", action="store_true", help="Ignore an existing generated progress checkpoint")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    fixed_set = _fixed_set()
    fixed_path = ROOT / "evidence/validation/translation-context-fixed-set.json"
    fixed_path.write_text(json.dumps({
        "schema_version": "1.0", "cases": fixed_set,
        "human_labels": "PENDING", "selection_policy": "deterministic real FINAL moments",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    qwen = QwenTranslationProvider(OpenAIJsonClient(OpenAIClientConfig(
        provider="ollama", api_key="ollama", base_url="http://127.0.0.1:11434/v1",
        model="qwen2.5:7b-instruct", timeout=45, max_retries=0, prefer_responses_api=False,
    )))
    argos = ArgosTranslationProvider()
    checkpoint = output / "translation-progress.json"
    results: list[dict] = (json.loads(checkpoint.read_text(encoding="utf-8"))
                           if checkpoint.is_file() and not args.restart else [])
    for index, case in enumerate(fixed_set[len(results):], start=len(results)):
        before = fixed_set[index - 1]["event_summary"] if index else ""
        after = fixed_set[index + 1]["event_summary"] if index + 1 < len(fixed_set) else ""
        context = {
            "context_before": before, "context_after": after,
            "event_summary": case["event_summary"], "creator": case["creator_id"],
            "content_type": case["category"], "recording": case["recording_title"],
        }
        started = time.perf_counter()
        try:
            qwen_rows = qwen.translate_group(
                case["cues"], source_language="en", target_language="zh", glossary={},
                mode=TranslationMode.LOCALIZED_CREATOR, context=context,
            )
        except Exception:
            # A local model may omit one ID in a large JSON array. Retry each missing
            # output with the entire semantic group retained in context; never accept
            # an incomplete group or silently drop speech.
            qwen_rows = []
            individual_context = {**context, "current_semantic_group": case["cues"]}
            for cue in case["cues"]:
                qwen_rows.extend(qwen.translate_group(
                    [cue], source_language="en", target_language="zh", glossary={},
                    mode=TranslationMode.LOCALIZED_CREATOR, context=individual_context,
                ))
        qwen_seconds = time.perf_counter() - started
        argos_rows: list[dict] = []
        argos_error = ""
        started = time.perf_counter()
        try:
            argos_rows = [{"cue_id": cue["cue_id"], "zh_text": argos.translate(
                cue["text"], source_language="en", target_language="zh", glossary={},
            )} for cue in case["cues"]]
        except Exception as exc:
            argos_error = str(exc)
        argos_seconds = time.perf_counter() - started
        results.append({
            **case, "context_before": before, "context_after": after,
            "qwen_contextual": qwen_rows, "argos": argos_rows,
            "argos_error": argos_error, "current_final": qwen_rows,
            "existing_user_edit": None, "timing_seconds": {
                "qwen": round(qwen_seconds, 3), "argos": round(argos_seconds, 3),
            }, "human_review": "PENDING",
        })
        checkpoint.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"translated contextual group {index + 1}/40", flush=True)
    comparison = output / "contextual-translation-comparison.json"
    comparison.write_text(json.dumps({
        "schema_version": "1.0", "cases": results, "human_review_required": True,
        "agent_naturalness_verdict": None,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Translation Quality Review", "", "Human review is required; no provider is pre-declared the winner.", ""]
    for case in results:
        lines.extend([f"## {case['case_id']} — {case['category']}", "",
                      f"Source: {' / '.join(cue['text'] for cue in case['cues'])}", "",
                      f"Context Before: {case['context_before']}", "",
                      f"Context After: {case['context_after']}", "",
                      f"Tone: {[row.get('tone', 'neutral') for row in case['qwen_contextual']]}", "",
                      f"Argos: {' / '.join(row.get('zh_text', '') for row in case['argos']) or '[UNAVAILABLE] ' + case['argos_error']}", "",
                      f"Qwen Contextual: {' / '.join(row.get('zh_text', '') for row in case['qwen_contextual'])}", "",
                      f"Current Final: {' / '.join(row.get('zh_text', '') for row in case['current_final'])}", "",
                      "Human: [ ] Argos Better  [ ] Qwen Better  [ ] Both Bad  [ ] Both Fine", "",
                      "Naturalness: [ ] GOOD  [ ] ACCEPTABLE  [ ] BAD", "",
                      "Meme/Slang: [ ] Preserved  [ ] Lost  [ ] Invented  [ ] N/A", "", "---", ""])
    (output / "translation-quality-review.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"cases": len(results), "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
