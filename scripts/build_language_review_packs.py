from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import zipfile

from acfv.clips import ArgosTranslationProvider, QwenTranslationProvider, translation_semantic_guard
from acfv.llm.openai_client import OpenAIClientConfig, OpenAIJsonClient


ROOT = Path(__file__).resolve().parents[1]


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _events(final_root: Path) -> list[dict]:
    rows = []
    for manifest_path in sorted(final_root.glob("*/*/standard/manifest.json")):
        manifest = _json(manifest_path)
        track_path = manifest_path.with_name("bilingual_track.json")
        transcript_path = Path(str(manifest.get("final_transcript_path") or ""))
        if not (track_path.is_file() and transcript_path.is_file()):
            raise FileNotFoundError(f"Incomplete language output: {manifest_path}")
        rows.append({
            "id": f"{manifest_path.parents[2].name}-{manifest_path.parents[1].name}",
            "event_root": manifest_path.parents[1], "manifest_path": manifest_path,
            "manifest": manifest, "track_path": track_path, "track": _json(track_path),
            "transcript_path": transcript_path, "transcript": _json(transcript_path),
        })
    if len(rows) < 12:
        raise RuntimeError(f"Expected 12 STANDARD language outputs, found {len(rows)}")
    return rows


def _build_asr_pack(events: list[dict], target: Path) -> dict:
    states: dict[str, int] = {}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as bundle:
        review_lines = ["# ASR Quality Review v2", "", "Human listening is required; flags are objective release signals.", ""]
        for row in events:
            transcript = row["transcript"]
            quality = dict(transcript.get("quality") or {})
            state = str(quality.get("final_quality_state") or "UNKNOWN")
            states[state] = states.get(state, 0) + 1
            sample = {
                "sample_id": row["id"],
                "event_context": row["manifest"].get("translation_context") or {},
                "raw_library_asr": transcript.get("raw_library_transcript") or "",
                "final_large_v3_asr": transcript.get("raw_final_asr") or "",
                "corrected_transcript": transcript.get("corrected_final_transcript") or "",
                "source_correction": transcript.get("correction") or {},
                "quality": quality,
                "words": transcript.get("aligned_words") or [],
                "local_redecode_evidence": transcript.get("local_redecode_evidence") or [],
                "human_review": "PENDING",
            }
            bundle.writestr(f"asr-v2/{row['id']}/review.json", json.dumps(sample, ensure_ascii=False, indent=2))
            audio = row["transcript_path"].parent / "event_with_context.wav"
            if audio.is_file():
                bundle.write(audio, f"asr-v2/{row['id']}/audio.wav")
            review_lines.extend([
                f"## {row['id']}", "", f"- State: {state}",
                f"- Low confidence: {quality.get('low_confidence_words', 0)} / {quality.get('total_words', 0)}",
                "- ASR: [ ] GOOD [ ] ACCEPTABLE [ ] BAD", "- Notes:", "", "---", "",
            ])
        bundle.writestr("asr-v2/review.md", "\n".join(review_lines))
    return {"samples": len(events), "states": states, "path": str(target)}


def _safe_translate(provider, text: str, glossary: dict[str, str]) -> dict:
    try:
        return {"status": "READY", "text": provider.translate(
            text, source_language="en", target_language="zh", glossary=glossary,
        )}
    except Exception as exc:
        return {"status": "UNAVAILABLE", "text": "", "error": f"{type(exc).__name__}: {exc}"}


def _build_translation_pack(events: list[dict], target: Path, *, live_comparisons: bool) -> dict:
    qwen = QwenTranslationProvider(OpenAIJsonClient(OpenAIClientConfig(
        provider="ollama", api_key="ollama", base_url="http://127.0.0.1:11434/v1",
        model="qwen2.5:7b-instruct", timeout=90, max_retries=0, prefer_responses_api=False,
    ))) if live_comparisons else None
    argos = ArgosTranslationProvider() if live_comparisons else None
    cases = []
    for row in events:
        context = dict(row["manifest"].get("translation_context") or {})
        glossary = dict(context.get("glossary") or {})
        corrected = str(row["transcript"].get("corrected_final_transcript") or "")
        raw = str(row["transcript"].get("raw_final_asr") or "")
        for cue in row["track"].get("cues") or []:
            source = str(cue.get("source_text") or "")
            contextual = str(cue.get("zh_text") or "")
            case = {
                "case_id": f"T{len(cases) + 1:02d}", "sample_id": row["id"],
                "source_raw": raw, "source_corrected": corrected, "source_cue": source,
                "context": context, "tone": cue.get("tone") or "neutral", "glossary": glossary,
                "argos": _safe_translate(argos, source, glossary) if argos else {"status": "NOT_RUN"},
                "qwen_v1": _safe_translate(qwen, source, glossary) if qwen else {"status": "NOT_RUN"},
                "qwen_contextual_v2": {
                    "status": "READY", "text": contextual,
                    "provider": cue.get("translation_provider") or row["track"].get("translation_provider"),
                    "attempt_count": cue.get("attempt_count", 1),
                },
                "quality_guard_results": translation_semantic_guard(source, contextual, glossary=glossary),
                "human_naturalness_review": "PENDING",
            }
            cases.append(case)
            if len(cases) >= 20:
                break
        if len(cases) >= 20:
            break
    lines = ["# Translation Quality Review v2", "", "No automated naturalness or meme-quality verdict is asserted.", ""]
    for case in cases:
        lines.extend([
            f"## {case['case_id']} / {case['sample_id']}", "", f"Source: {case['source_cue']}", "",
            f"Argos: {case['argos'].get('text') or '[' + case['argos']['status'] + ']' }", "",
            f"Qwen v1: {case['qwen_v1'].get('text') or '[' + case['qwen_v1']['status'] + ']' }", "",
            f"Qwen contextual v2: {case['qwen_contextual_v2']['text']}", "",
            "Human: [ ] v1 Better [ ] v2 Better [ ] Argos Better [ ] All Need Edit", "", "---", "",
        ])
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as bundle:
        bundle.writestr("translation-v2/cases.json", json.dumps({
            "schema_version": "2.0", "cases": cases,
            "agent_naturalness_verdict": None, "human_review": "PENDING",
        }, ensure_ascii=False, indent=2))
        bundle.writestr("translation-v2/review.md", "\n".join(lines))
    return {
        "cases": len(cases), "path": str(target),
        "qwen_v1_ready": sum(case["qwen_v1"].get("status") == "READY" for case in cases),
        "argos_ready": sum(case["argos"].get("status") == "READY" for case in cases),
    }


def _build_final_pack(events: list[dict], asr_pack: Path, translation_pack: Path, target: Path) -> dict:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as bundle:
        bundle.write(asr_pack, asr_pack.name)
        bundle.write(translation_pack, translation_pack.name)
        for row in events:
            event_root = row["event_root"]
            for path in (
                event_root / "FINAL_STANDARD.mp4", row["manifest_path"], row["track_path"],
                row["manifest_path"].with_name("clip_zh_en.ass"),
                row["manifest_path"].with_name("clip_zh_en.srt"),
                row["manifest_path"].with_name("subtitle_timeline_report.json"),
                row["manifest_path"].with_name("final_language_quality.json"),
                row["transcript_path"], row["transcript_path"].with_name("final_transcript_quality.json"),
            ):
                if path.is_file():
                    bundle.write(path, Path("final-language-review") / row["id"] / path.name)
    size = target.stat().st_size
    if size > 500 * 1024 * 1024:
        raise RuntimeError(f"Final review pack exceeds 500 MiB: {size}")
    return {"clips": len(events), "bytes": size, "path": str(target)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--final-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=ROOT / "var/final_language_quality")
    parser.add_argument("--skip-live-comparisons", action="store_true")
    parser.add_argument("--reuse-translation-pack", action="store_true",
                        help="Keep an already validated v2 translation comparison archive")
    args = parser.parse_args()
    output = args.output_root.resolve()
    output.mkdir(parents=True, exist_ok=True)
    events = _events(args.final_root.resolve())
    asr_pack = output / "asr-quality-review-bundle-v2.zip"
    translation_pack = output / "translation-quality-review-bundle-v2.zip"
    final_pack = output / "final-language-quality-review-pack.zip"
    translation_report = (
        {"path": str(translation_pack), "reused": True}
        if args.reuse_translation_pack and translation_pack.is_file()
        else _build_translation_pack(events, translation_pack,
                                     live_comparisons=not args.skip_live_comparisons)
    )
    report = {"asr": _build_asr_pack(events, asr_pack), "translation": translation_report}
    report["final"] = _build_final_pack(events, asr_pack, translation_pack, final_pack)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
