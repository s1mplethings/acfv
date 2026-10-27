from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pysubs2

from .blockify import SubtitleBlock, SubtitleEvent, build_blocks
from .backends.argos import ArgosBackend
from .backends.llm_json import LlmJsonBackend
from .backends.nllb_local import NllbLocalBackend
from .backends.seamless_local import SeamlessLocalBackend
from .writer import write_translated

logger = logging.getLogger(__name__)


@dataclass
class TranslationConfig:
    enabled: bool = False
    engine: str = "llm_json"
    target_lang: str = "zh-Hans"
    source_lang: str = "en"
    bilingual: bool = False
    merge_mode: str = "lock_timeline"
    block_max_duration: float = 10.0
    block_max_chars: int = 350
    block_max_gap: float = 0.6
    block_min_items: int = 2
    llm_api_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_system_prompt: str = ""


def run_translate_streamer_subtitles(run_dir: Path, config: Dict[str, object]) -> Dict[str, object]:
    cfg = _load_config(config)
    work_dir = Path(run_dir) / "work"

    if not cfg.enabled:
        return {"status": "disabled"}

    source_path = _find_source_subtitle(work_dir)
    if not source_path:
        return {"status": "missing_source"}

    events = _load_events(source_path)
    if not events:
        return {"status": "empty"}

    blocks = build_blocks(
        events,
        max_duration_sec=cfg.block_max_duration,
        max_chars=cfg.block_max_chars,
        max_gap_sec=cfg.block_max_gap,
        min_items=cfg.block_min_items,
    )

    backend = _build_backend(cfg)
    cache_path = work_dir / "translation_cache.jsonl"
    cache = _load_cache(cache_path)

    translations: Dict[str, str] = {}
    for block in blocks:
        block_key = _cache_key(block, cfg)
        cached = cache.get(block_key)
        if cached:
            translations.update(cached)
            continue

        try:
            translated = backend.translate_block(block)
        except Exception as exc:
            logger.warning("[subtitle_translate] block translation failed: %s", exc)
            translated = {}

        missing = [event for event in block.events if event.event_id not in translated]
        if missing:
            fallback = backend.translate_lines(missing)
            translated.update(fallback)

        translations.update(translated)
        if translated:
            _append_cache(cache_path, block_key, translated)
            cache[block_key] = translated

    zh_srt = work_dir / "streamer.zh.srt"
    zh_ass = work_dir / "streamer.zh.ass"
    bilingual_ass = work_dir / "streamer.bilingual.ass"

    write_translated(source_path, events, translations, zh_srt, bilingual=False)
    write_translated(source_path, events, translations, zh_ass, bilingual=False)
    if cfg.bilingual:
        write_translated(source_path, events, translations, bilingual_ass, bilingual=True)

    return {
        "status": "ok",
        "source": str(source_path),
        "zh_srt": str(zh_srt),
        "zh_ass": str(zh_ass),
        "bilingual_ass": str(bilingual_ass) if cfg.bilingual else None,
        "cache_path": str(cache_path),
        "count": len(events),
        "engine": cfg.engine,
    }


def _load_config(raw: Dict[str, object]) -> TranslationConfig:
    return TranslationConfig(
        enabled=bool(raw.get("enabled", False)),
        engine=str(raw.get("engine", "llm_json")),
        target_lang=str(raw.get("target_lang", "zh-Hans")),
        source_lang=str(raw.get("source_lang", "en")),
        bilingual=bool(raw.get("bilingual", False)),
        merge_mode=str(raw.get("merge_mode", "lock_timeline")),
        block_max_duration=float(raw.get("block_max_duration", 10.0)),
        block_max_chars=int(raw.get("block_max_chars", 350)),
        block_max_gap=float(raw.get("block_max_gap", 0.6)),
        block_min_items=int(raw.get("block_min_items", 2)),
        llm_api_url=str(raw.get("llm_api_url", "")),
        llm_api_key=str(raw.get("llm_api_key", "")),
        llm_model=str(raw.get("llm_model", "")),
        llm_system_prompt=str(raw.get("llm_system_prompt", "")),
    )


def _find_source_subtitle(work_dir: Path) -> Optional[Path]:
    candidates = [
        work_dir / "subtitles_streamer.ass",
        work_dir / "subtitles_streamer.srt",
        work_dir / "subtitles.ass",
        work_dir / "subtitles.srt",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _load_events(source_path: Path) -> List[SubtitleEvent]:
    subs = pysubs2.load(str(source_path))
    events: List[SubtitleEvent] = []
    for idx, event in enumerate(subs.events):
        text = event.text.replace(r"\N", " ").replace("\n", " ").strip()
        text = pysubs2.clean_tags(text)
        event_id = f"{idx + 1:04d}"
        events.append(
            SubtitleEvent(
                event_id=event_id,
                start_ms=int(event.start),
                end_ms=int(event.end),
                text=text,
                index=idx,
            )
        )
    return events


def _build_backend(cfg: TranslationConfig):
    engine = cfg.engine.strip().lower()
    if engine == "llm_json":
        if not cfg.llm_api_url:
            raise ValueError("llm_api_url is required for llm_json backend")
        return LlmJsonBackend(
            api_url=cfg.llm_api_url,
            api_key=cfg.llm_api_key or None,
            model=cfg.llm_model or "default",
            system_prompt=cfg.llm_system_prompt or "",
        )
    if engine == "argos":
        return ArgosBackend(source_lang=cfg.source_lang, target_lang=_short_lang(cfg.target_lang))
    if engine == "nllb":
        return NllbLocalBackend()
    if engine == "seamless":
        return SeamlessLocalBackend()
    raise ValueError(f"Unknown translation engine: {cfg.engine}")


def _short_lang(lang: str) -> str:
    text = (lang or "").lower()
    if text.startswith("zh"):
        return "zh"
    if text.startswith("en"):
        return "en"
    return text or "en"


def _cache_key(block: SubtitleBlock, cfg: TranslationConfig) -> str:
    payload = {
        "engine": cfg.engine,
        "target_lang": cfg.target_lang,
        "block": block.block_text(),
    }
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_cache(path: Path) -> Dict[str, Dict[str, str]]:
    cache: Dict[str, Dict[str, str]] = {}
    if not path.exists():
        return cache
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            key = data.get("key")
            items = data.get("items")
            if isinstance(key, str) and isinstance(items, dict):
                cache[key] = {str(k): str(v) for k, v in items.items()}
    except Exception as exc:
        logger.warning("[subtitle_translate] failed to load cache: %s", exc)
    return cache


def _append_cache(path: Path, key: str, items: Dict[str, str]) -> None:
    record = {"key": key, "items": items}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


__all__ = ["run_translate_streamer_subtitles"]
