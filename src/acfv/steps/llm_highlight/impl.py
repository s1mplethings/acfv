from __future__ import annotations

import json
import logging
import socket
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Dict, Iterable, List, Optional, Tuple

from acfv.llm import JsonSchemaValidationError, get_default_client

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
UNITS = "ms"
SORT_POLICY = "score_desc_start_ms_asc_end_ms_asc"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_text(value: Any, default: str = "") -> str:
    try:
        return str(value or "").strip()
    except Exception:
        return default


def _normalize_transcript(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        items = payload.get("segments", [])
    else:
        items = payload or []
    out: List[Dict[str, Any]] = []
    for seg in items:
        if not isinstance(seg, dict):
            continue
        start = _safe_float(seg.get("start"), 0.0)
        end = _safe_float(seg.get("end"), 0.0)
        text = str(seg.get("text") or "").strip()
        if end <= start:
            continue
        out.append({"start": start, "end": end, "text": text})
    return out


def _normalize_chat(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        items = payload.get("records", [])
        if not isinstance(items, list):
            fallback = payload.get("messages", [])
            items = fallback if isinstance(fallback, list) else []
    else:
        items = payload or []
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ts = _safe_float(item.get("timestamp", item.get("time", item.get("t", 0.0))), 0.0)
        text = str(item.get("message") or item.get("text") or "").strip()
        out.append({"timestamp": ts, "message": text})
    return out


def _normalize_timeline(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        items = payload.get("timeline", [])
    else:
        items = payload or []
    out: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        start = _safe_float(item.get("start_sec", item.get("start")), 0.0)
        end = _safe_float(item.get("end_sec", item.get("end")), 0.0)
        if end <= start:
            continue
        out.append(item)
    return out


def _normalize_emotion(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        start = _safe_float(item.get("start"), 0.0)
        end = _safe_float(item.get("end"), 0.0)
        score = _safe_float(item.get("score"), 0.0)
        if end <= start:
            continue
        out.append({"start": start, "end": end, "score": score})
    return out


def _normalize_candidates(payload: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    policy = payload.get("policy", {}) if isinstance(payload, dict) else {}
    items = payload.get("segments", []) if isinstance(payload, dict) else payload or []
    out: List[Dict[str, Any]] = []
    for idx, seg in enumerate(items):
        if not isinstance(seg, dict):
            continue
        if "start_ms" in seg or "end_ms" in seg:
            start = _safe_float(seg.get("start_ms"), 0.0) / 1000.0
            end = _safe_float(seg.get("end_ms"), 0.0) / 1000.0
        else:
            start = _safe_float(seg.get("start"), 0.0)
            end = _safe_float(seg.get("end"), 0.0)
        if end <= start:
            continue
        out.append(
            {
                "candidate_id": f"cand_{idx + 1:03d}",
                "start": start,
                "end": end,
                "score": _safe_float(seg.get("score"), 0.0),
                "rank": _safe_int(seg.get("rank"), idx + 1),
                "text": str(seg.get("text") or "").strip(),
                "reason_tags": [str(tag) for tag in (seg.get("reason_tags") or []) if str(tag)],
                "score_base": seg.get("score_base"),
                "score_scale": seg.get("score_scale"),
                "overlap_count": seg.get("overlap_count"),
            }
        )
    return out, policy if isinstance(policy, dict) else {}


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _snippet_transcript(transcript: Iterable[Dict[str, Any]], start: float, end: float, limit_chars: int = 600) -> str:
    texts: List[str] = []
    size = 0
    for seg in transcript:
        if _overlap(start, end, _safe_float(seg.get("start")), _safe_float(seg.get("end"))) <= 0:
            continue
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        texts.append(text)
        size += len(text)
        if size >= limit_chars:
            break
    return " ".join(texts)[:limit_chars]


def _snippet_chat(chat: Iterable[Dict[str, Any]], start: float, end: float, limit_items: int = 10) -> List[str]:
    lines: List[str] = []
    for item in chat:
        ts = _safe_float(item.get("timestamp"), 0.0)
        if start <= ts <= end:
            text = str(item.get("message") or "").strip()
            if text:
                lines.append(text)
        if len(lines) >= limit_items:
            break
    return lines


def _chat_context(chat: Iterable[Dict[str, Any]], start: float, end: float) -> Dict[str, Any]:
    window: List[str] = []
    authors = Counter()
    for item in chat:
        ts = _safe_float(item.get("timestamp"), 0.0)
        if not (start <= ts <= end):
            continue
        text = str(item.get("message") or "").strip()
        if text:
            window.append(text)
        author = str(item.get("author") or "").strip()
        if author:
            authors[author] += 1
    top_messages = [
        {"text": text, "count": count}
        for text, count in Counter(window).most_common(5)
        if text
    ]
    return {
        "count": len(window),
        "samples": window[:10],
        "top_messages": top_messages,
        "top_authors": [{"author": name, "count": count} for name, count in authors.most_common(5)],
    }


def _screen_context(timeline: Iterable[Dict[str, Any]], start: float, end: float, limit_items: int = 3) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for item in timeline:
        if _overlap(start, end, _safe_float(item.get("start_sec", item.get("start"))), _safe_float(item.get("end_sec", item.get("end")))) <= 0:
            continue
        items.append(
            {
                "screen_type": item.get("screen_type") or item.get("screen_label"),
                "app_guess": item.get("app_guess") or item.get("app_or_site"),
                "activity": item.get("activity") or item.get("activity_summary"),
                "summary": item.get("summary") or item.get("activity_summary"),
                "entities": item.get("entities") or [],
                "confidence": item.get("confidence"),
                "ocr_text_hint": item.get("ocr_text_hint") or "",
            }
        )
        if len(items) >= limit_items:
            break
    return items


def _emotion_average(items: Iterable[Dict[str, Any]], start: float, end: float) -> float:
    numerator = 0.0
    denominator = 0.0
    for item in items:
        overlap = _overlap(start, end, _safe_float(item.get("start")), _safe_float(item.get("end")))
        if overlap <= 0:
            continue
        numerator += overlap * _safe_float(item.get("score"), 0.0)
        denominator += overlap
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _passthrough_segments(candidates: List[Dict[str, Any]], policy: Dict[str, Any], reason: str) -> Dict[str, Any]:
    segments: List[Dict[str, Any]] = []
    for rank, seg in enumerate(sorted(candidates, key=lambda item: (-item["score"], item["start"], item["end"])), start=1):
        segments.append(
            {
                "start_ms": int(round(seg["start"] * 1000)),
                "end_ms": int(round(seg["end"] * 1000)),
                "score": float(seg.get("score", 0.0)),
                "rank": rank,
                "highlight_type": "rule_based",
                "summary": seg.get("text", "")[:160],
                "reason_tags": seg.get("reason_tags") or ["rule_based"],
                "why_highlight": reason,
                "confidence": 0.25,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "units": UNITS,
        "sort": SORT_POLICY,
        "policy": {
            **policy,
            "source": "llm_highlight_passthrough",
            "fallback_reason": reason,
            "max_segments": len(segments),
        },
        "segments": segments,
    }


def _schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "segments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "start": {"type": "number"},
                        "end": {"type": "number"},
                        "score": {"type": "number"},
                        "highlight_type": {"type": "string"},
                        "summary": {"type": "string"},
                        "reason_tags": {"type": "array", "items": {"type": "string"}},
                        "why_highlight": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": [
                        "candidate_id",
                        "score",
                        "highlight_type",
                        "summary",
                        "reason_tags",
                        "why_highlight",
                        "confidence",
                    ],
                    "additionalProperties": True,
                },
            }
        },
        "required": ["segments"],
        "additionalProperties": True,
    }


def _distill_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "distilled_summary": {"type": "string"},
                        "interest_tags": {"type": "array", "items": {"type": "string"}},
                        "chat_takeaway": {"type": "string"},
                        "screen_takeaway": {"type": "string"},
                        "transcript_takeaway": {"type": "string"},
                        "user_interest_fit": {"type": "string"},
                    },
                    "required": ["candidate_id", "distilled_summary"],
                    "additionalProperties": True,
                },
            }
        },
        "required": ["candidates"],
        "additionalProperties": True,
    }


def _validate_distill_output(payload: Dict[str, Any], candidate_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    items = payload.get("candidates")
    if not isinstance(items, list):
        raise JsonSchemaValidationError("candidates must be a list")
    out: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        candidate_id = _safe_text(item.get("candidate_id"))
        if candidate_id not in candidate_map:
            continue
        out.append(
            {
                "candidate_id": candidate_id,
                "distilled_summary": _safe_text(item.get("distilled_summary")),
                "interest_tags": [_safe_text(tag) for tag in (item.get("interest_tags") or []) if _safe_text(tag)],
                "chat_takeaway": _safe_text(item.get("chat_takeaway")),
                "screen_takeaway": _safe_text(item.get("screen_takeaway")),
                "transcript_takeaway": _safe_text(item.get("transcript_takeaway")),
                "user_interest_fit": _safe_text(item.get("user_interest_fit")),
            }
        )
    return {"candidates": out}


def _validate_llm_output(payload: Dict[str, Any], candidate_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    items = payload.get("segments")
    if not isinstance(items, list):
        raise JsonSchemaValidationError("segments must be a list")
    if not items:
        return {"segments": []}
    out: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidate_id") or "").strip()
        if candidate_id not in candidate_map:
            continue
        candidate = candidate_map[candidate_id]
        start = _safe_float(item.get("start"), candidate["start"])
        end = _safe_float(item.get("end"), candidate["end"])
        if end <= start:
            start = candidate["start"]
            end = candidate["end"]
        start = max(candidate["start"], start)
        end = min(candidate["end"], end)
        if end <= start:
            start = candidate["start"]
            end = candidate["end"]
        out.append(
            {
                "candidate_id": candidate_id,
                "start": start,
                "end": end,
                "score": max(0.0, _safe_float(item.get("score"), candidate.get("score", 0.0))),
                "highlight_type": str(item.get("highlight_type") or "semantic_highlight").strip(),
                "summary": str(item.get("summary") or "").strip(),
                "reason_tags": [str(tag).strip() for tag in (item.get("reason_tags") or []) if str(tag).strip()],
                "why_highlight": str(item.get("why_highlight") or "").strip(),
                "confidence": max(0.0, min(1.0, _safe_float(item.get("confidence"), 0.0))),
            }
        )
    if not out:
        raise JsonSchemaValidationError("LLM returned no valid highlight segments")
    return {"segments": out}


def _cfg_bool(config_manager: Any, key: str, default: bool) -> bool:
    if config_manager is None:
        return default
    try:
        value = config_manager.get(key, default)
    except Exception:
        return default
    if isinstance(value, bool):
        return value
    text = _safe_text(value).lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _cfg_text(config_manager: Any, key: str, default: str = "") -> str:
    if config_manager is None:
        return default
    try:
        return _safe_text(config_manager.get(key, default), default)
    except Exception:
        return default


def _is_quickly_reachable(base_url: str) -> bool:
    parsed = urlparse(base_url or "")
    host = parsed.hostname
    port = parsed.port
    if not host:
        return True
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    if host not in {"127.0.0.1", "localhost"}:
        return True
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _distill_candidates_local(
    *,
    llm_candidates: List[Dict[str, Any]],
    candidate_map: Dict[str, Dict[str, Any]],
    config_manager: Any,
    user_interest_prompt: str,
) -> List[Dict[str, Any]]:
    enabled = _cfg_bool(config_manager, "ENABLE_LLM_LOCAL_DISTILL", True)
    if not enabled or not llm_candidates:
        return llm_candidates

    local_model = _cfg_text(config_manager, "LLM_LOCAL_MODEL", "")
    client = get_default_client(config_manager=config_manager, model=local_model or None, prefix="LLM_LOCAL")
    if not client.available:
        return llm_candidates
    base_url = _safe_text(getattr(getattr(client, "config", None), "base_url", ""))
    if base_url and not _is_quickly_reachable(base_url):
        logger.info("[llm_highlight] local distill skipped, Ollama/OpenAI-compatible endpoint unreachable: %s", base_url)
        return llm_candidates

    system_prompt = (
        "You are a local distillation pass for streamer highlight selection. "
        "Compress each candidate into a dense semantic summary for a stronger downstream reranker. "
        "Return only JSON."
    )
    preference_block = f"\nUser preference: {user_interest_prompt}" if user_interest_prompt else ""
    user_prompt = (
        "For each candidate below, write a short distilled_summary and a few interest_tags. "
        "Focus on what is actually happening on screen and in speech/chat."
        f"{preference_block}\n"
        + json.dumps({"candidates": llm_candidates}, ensure_ascii=False, indent=2)
    )
    try:
        payload = client.complete_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=_distill_schema(),
            validator=lambda item: _validate_distill_output(item, candidate_map),
            temperature=0.0,
        )
    except Exception as exc:
        logger.info("[llm_highlight] local distill unavailable, continue with raw candidates: %s", exc)
        return llm_candidates

    distilled_by_id = {item["candidate_id"]: item for item in payload.get("candidates", [])}
    merged: List[Dict[str, Any]] = []
    for candidate in llm_candidates:
        extra = distilled_by_id.get(candidate["candidate_id"], {})
        merged_item = dict(candidate)
        if extra:
            merged_item["local_distill"] = {
                "distilled_summary": extra.get("distilled_summary", ""),
                "interest_tags": extra.get("interest_tags", []),
                "chat_takeaway": extra.get("chat_takeaway", ""),
                "screen_takeaway": extra.get("screen_takeaway", ""),
                "transcript_takeaway": extra.get("transcript_takeaway", ""),
                "user_interest_fit": extra.get("user_interest_fit", ""),
            }
        merged.append(merged_item)
    return merged


def run_llm_highlight(
    *,
    semantic_segments_payload: Any,
    candidate_segments_payload: Any,
    transcript_payload: Any,
    chat_payload: Any,
    screen_payload: Any,
    video_emotion_payload: Any,
    work_dir: Path,
    config_manager: Any = None,
    enabled: bool | None = None,
    max_candidates_override: int | None = None,
    target_segments_override: int | None = None,
    progress_callback=None,
) -> Dict[str, Any]:
    candidates, policy = _normalize_candidates(semantic_segments_payload or candidate_segments_payload)
    if not candidates:
        return _passthrough_segments([], policy, "no_candidates")

    transcript = _normalize_transcript(transcript_payload)
    chat = _normalize_chat(chat_payload)
    screen_timeline = _normalize_timeline(screen_payload)
    emotions = _normalize_emotion(video_emotion_payload)

    enabled_cfg = enabled
    max_candidates = 8
    target_segments: Optional[int] = None
    require_api = False
    user_interest_prompt = ""
    if config_manager is not None:
        try:
            if enabled_cfg is None:
                enabled_cfg = bool(config_manager.get("ENABLE_LLM_HIGHLIGHT", False))
            max_candidates = max(1, int(config_manager.get("LLM_HIGHLIGHT_MAX_CANDIDATES", max_candidates)))
            target_segments = _safe_int(config_manager.get("MAX_CLIP_COUNT", 0), 0) or None
            require_api = bool(config_manager.get("REQUIRE_LLM_API", False))
            user_interest_prompt = _safe_text(config_manager.get("LLM_HIGHLIGHT_USER_PREFERENCE_PROMPT", ""))
        except Exception:
            enabled_cfg = False if enabled_cfg is None else enabled_cfg
            require_api = False
    if max_candidates_override is not None:
        max_candidates = max(1, int(max_candidates_override))
    if target_segments_override is not None:
        target_segments = max(1, int(target_segments_override))
    if enabled_cfg is None:
        enabled_cfg = False
    chosen = sorted(candidates, key=lambda item: (-item["score"], item["start"], item["end"]))[:max_candidates]
    candidate_map = {item["candidate_id"]: item for item in chosen}

    if not enabled_cfg:
        payload = _passthrough_segments(chosen, policy, "llm_highlight_disabled")
        (work_dir / "segments_llm.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    llm_candidates: List[Dict[str, Any]] = []
    for candidate in chosen:
        start = candidate["start"]
        end = candidate["end"]
        llm_candidates.append(
            {
                "candidate_id": candidate["candidate_id"],
                "start": round(start, 3),
                "end": round(end, 3),
                "rule_score": round(float(candidate.get("score", 0.0)), 4),
                "transcript": _snippet_transcript(transcript, start, end),
                "chat_context": _chat_context(chat, start, end),
                "screen_context": _screen_context(screen_timeline, start, end),
                "video_emotion": round(_emotion_average(emotions, start, end), 4),
                "reason_tags": candidate.get("reason_tags") or [],
            }
        )

    llm_candidates = _distill_candidates_local(
        llm_candidates=llm_candidates,
        candidate_map=candidate_map,
        config_manager=config_manager,
        user_interest_prompt=user_interest_prompt,
    )

    client = get_default_client(config_manager=config_manager, prefix="LLM_HIGHLIGHT")
    if not client.available:
        reason = client.availability_error() or "llm_client_unavailable"
        if require_api:
            raise RuntimeError(
                f"llm_highlight requires an enabled LLM provider, but client is unavailable: {reason}. "
                "Set providers.llm or LLM_PROVIDER/LLM_BASE_URL/LLM_MODEL."
            )
        payload = _passthrough_segments(chosen, policy, reason)
        (work_dir / "segments_llm.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload
    client_config = getattr(client, "config", None)
    provider_name = _safe_text(getattr(client_config, "provider", "")).lower()
    base_url = _safe_text(getattr(client_config, "base_url", ""))
    if provider_name in {"ollama", "vllm", "openai-compatible", "local-openai"} and base_url:
        if not _is_quickly_reachable(base_url):
            reason = f"llm_endpoint_unreachable:{base_url}"
            if require_api:
                raise RuntimeError(
                    "llm_highlight requires a reachable local LLM endpoint, "
                    f"but {base_url} is unavailable."
                )
            payload = _passthrough_segments(chosen, policy, reason)
            (work_dir / "segments_llm.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return payload

    if progress_callback:
        progress_callback("llm_highlight", 0, 1, "start")

    system_prompt = (
        "You are reranking highlight candidates for a streamer clip pipeline. "
        "Use transcript, chat, screen context and emotion signals together. "
        "Return only JSON."
    )
    preference_block = f"\nUser preference prompt:\n{user_interest_prompt}\n" if user_interest_prompt else ""
    user_prompt = (
        "Given the candidate highlight windows below, rerank the best highlights.\n"
        + (f"Target final clip count: {target_segments}.\n" if target_segments else "")
        + "Prefer semantically meaningful moments such as coding breakthroughs, visible tooling activity, "
        + "browser/docs reading tied to problem solving, GitHub/code review, terminal execution, or strong gameplay/result moments.\n"
        + "You may keep the candidate start/end or tighten them inside the candidate range.\n"
        + "Return a JSON object with key `segments`.\n"
        + "If none of the candidates are actually highlight-worthy, return exactly {\"segments\": []}.\n"
        + "If you keep any segment, every kept item must include candidate_id, score, highlight_type, summary, reason_tags, why_highlight, confidence.\n"
        + "Use local_distill if present as a compressed semantic hint, but do not ignore raw transcript/chat/screen evidence.\n"
        + f"{preference_block}"
        + json.dumps({"candidates": llm_candidates}, ensure_ascii=False, indent=2)
    )
    try:
        llm_payload = client.complete_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=_schema(),
            validator=lambda payload: _validate_llm_output(payload, candidate_map),
            temperature=0.0,
        )
        final_items = llm_payload["segments"]
    except Exception as exc:
        logger.warning("[llm_highlight] llm rerank failed: %s", exc)
        if require_api:
            raise RuntimeError(f"llm_highlight requires an enabled LLM provider and rerank failed: {exc}") from exc
        payload = _passthrough_segments(chosen, policy, f"llm_failed:{exc}")
        (work_dir / "segments_llm.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if progress_callback:
            progress_callback("llm_highlight", 1, 1, "fallback")
        return payload

    segments: List[Dict[str, Any]] = []
    ordered_items = sorted(final_items, key=lambda seg: (-seg["score"], seg["start"], seg["end"]))
    if target_segments:
        ordered_items = ordered_items[:target_segments]
    for rank, item in enumerate(ordered_items, start=1):
        segments.append(
            {
                "start_ms": int(round(item["start"] * 1000)),
                "end_ms": int(round(item["end"] * 1000)),
                "score": float(item["score"]),
                "rank": rank,
                "highlight_type": item["highlight_type"],
                "summary": item["summary"],
                "reason_tags": item["reason_tags"],
                "why_highlight": item["why_highlight"],
                "confidence": item["confidence"],
            }
        )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "units": UNITS,
        "sort": SORT_POLICY,
        "policy": {
            **policy,
            "source": "llm_highlight",
            "max_segments": len(segments),
            "candidate_count": len(chosen),
            "target_segments": target_segments,
        },
        "segments": segments,
    }
    (work_dir / "segments_llm.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if progress_callback:
        progress_callback("llm_highlight", 1, 1, "done")
    return payload


__all__ = ["run_llm_highlight"]
