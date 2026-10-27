from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Protocol

from pydantic import BaseModel, ConfigDict, Field


class BilingualDisplayMode(str, Enum):
    ZH_EN = "ZH_EN"
    EN_ZH = "EN_ZH"
    ZH_ONLY = "ZH_ONLY"
    EN_ONLY = "EN_ONLY"
    SOURCE_ONLY = "SOURCE_ONLY"
    SOURCE_ZH = "SOURCE_ZH"
    SOURCE_EN = "SOURCE_EN"


class SubtitleCompleteness(str, Enum):
    COMPLETE = "COMPLETE"
    CLEAN = "CLEAN"


class TranslationRuntimeStatus(str, Enum):
    READY = "TRANSLATION_READY"
    DEGRADED = "TRANSLATION_DEGRADED"
    UNAVAILABLE = "TRANSLATION_UNAVAILABLE"


class TranslationMode(str, Enum):
    FAITHFUL = "FAITHFUL"
    LOCALIZED_CREATOR = "LOCALIZED_CREATOR"


class SubtitlePosition(str, Enum):
    TOP = "TOP"
    BOTTOM = "BOTTOM"
    AUTO_SAFE_AREA = "AUTO_SAFE_AREA"


class SemanticImportance(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SemanticPosition(str, Enum):
    SETUP = "SETUP"
    CONTEXT = "CONTEXT"
    CORE = "CORE"
    PAYOFF = "PAYOFF"
    AFTERMATH = "AFTERMATH"


class LanguageIssueSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TranslationIssueCategory(str, Enum):
    CRITICAL_SEMANTIC = "CRITICAL_SEMANTIC"
    FACTUAL = "FACTUAL"
    TERMINOLOGY = "TERMINOLOGY"
    STYLE = "STYLE"
    NATURALNESS = "NATURALNESS"
    STRUCTURAL = "STRUCTURAL"


class EntityType(str, Enum):
    KNOWN_CREATOR_ENTITY = "KNOWN_CREATOR_ENTITY"
    GAME_TERM = "GAME_TERM"
    OCR_CONFIRMED_ENTITY = "OCR_CONFIRMED_ENTITY"
    GLOSSARY_ENTITY = "GLOSSARY_ENTITY"
    REPEATED_HIGH_CONFIDENCE_ENTITY = "REPEATED_HIGH_CONFIDENCE_ENTITY"
    UNKNOWN_CAPITALIZED_TOKEN = "UNKNOWN_CAPITALIZED_TOKEN"


_IMPORTANCE_WEIGHT = {"LOW": 0.5, "MEDIUM": 1.0, "HIGH": 1.6, "CRITICAL": 2.2}
_POSITION_WEIGHT = {"SETUP": 0.8, "CONTEXT": 0.9, "CORE": 1.3, "PAYOFF": 1.6, "AFTERMATH": 0.7}
_SEVERITY_WEIGHT = {"INFO": 0.25, "WARNING": 1.0, "HIGH": 2.0, "CRITICAL": 3.0}


@dataclass(frozen=True)
class LanguageIssueCluster:
    """One release-gate unit backed by a single underlying language problem."""

    cluster_id: str
    clip_id: str
    start_ms: int
    end_ms: int
    root_cause: str
    member_findings: tuple[dict[str, Any], ...]
    max_severity: str
    semantic_importance: str
    semantic_position: str
    evidence: tuple[dict[str, Any], ...]
    cluster_risk: float
    recommended_action: str
    hard_blocker: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _stable_issue_key(parts: Iterable[object]) -> str:
    payload = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _issue_span(item: dict[str, Any]) -> tuple[int, int]:
    start = int(item.get("start_ms", item.get("timestamp", 0)) or 0)
    end = int(item.get("end_ms", start) or start)
    return min(start, end), max(start, end)


def _issue_root_cause(item: dict[str, Any]) -> str:
    explicit = str(item.get("root_cause_key") or "").strip()
    if explicit:
        return explicit
    # Legacy findings did not persist a source span. Keep them separate rather
    # than guessing from timestamp proximity and hiding an independent issue.
    return "legacy:" + _stable_issue_key((item.get("issue_id"), item.get("type")))


def cluster_language_issues(issues: Iterable[dict[str, Any]], *,
                            clip_id: str = "") -> list[LanguageIssueCluster]:
    """Deduplicate corroborating findings without weakening hard blockers."""
    root_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for original in issues:
        item = dict(original)
        root = _issue_root_cause(item)
        consequence = str(item.get("semantic_consequence") or item.get("type") or "UNKNOWN")
        root_groups.setdefault((root, consequence), []).append(item)

    # A recurring token/rule later in the clip is a new problem.  Split each
    # root into overlap-connected components before applying deduplication.
    groups: list[tuple[str, str, list[dict[str, Any]]]] = []
    for (root, consequence), candidates in root_groups.items():
        current: list[dict[str, Any]] = []
        current_end = -1
        for item in sorted(candidates, key=lambda row: _issue_span(row)):
            start, end = _issue_span(item)
            if current and start > current_end:
                groups.append((root, consequence, current))
                current = []
                current_end = -1
            current.append(item)
            current_end = max(current_end, end)
        if current:
            groups.append((root, consequence, current))

    clusters: list[LanguageIssueCluster] = []
    severity_rank = {name: index for index, name in enumerate(("INFO", "WARNING", "HIGH", "CRITICAL"))}
    importance_rank = {name: index for index, name in enumerate(("LOW", "MEDIUM", "HIGH", "CRITICAL"))}
    position_rank = {name: index for index, name in enumerate(("AFTERMATH", "SETUP", "CONTEXT", "CORE", "PAYOFF"))}
    for root, consequence, members in groups:
        starts_ends = [_issue_span(item) for item in members]
        primary = max(float(item.get("risk_contribution") or 0.0) for item in members)
        evidence_sources = {
            str(item.get("evidence_source") or (item.get("evidence") or {}).get("source") or "same-rule")
            for item in members
        }
        bonus = min(primary * 0.25, primary * 0.10 * max(0, len(evidence_sources) - 1))
        max_severity = max(
            (str(item.get("severity") or "INFO") for item in members),
            key=lambda value: severity_rank.get(value, -1),
        )
        importance = max(
            (str(item.get("semantic_importance") or "LOW") for item in members),
            key=lambda value: importance_rank.get(value, -1),
        )
        position = max(
            (str(item.get("semantic_position") or "CONTEXT") for item in members),
            key=lambda value: position_rank.get(value, -1),
        )
        hard = any(bool(item.get("hard_blocker")) for item in members)
        action = "BLOCK_RELEASE" if hard else str(
            max(members, key=lambda item: float(item.get("risk_contribution") or 0.0)).get(
                "recommended_action", "REVIEW"
            )
        )
        clusters.append(LanguageIssueCluster(
            cluster_id="language-cluster:" + _stable_issue_key((clip_id, root, consequence)),
            clip_id=clip_id,
            start_ms=min(start for start, _ in starts_ends),
            end_ms=max(end for _, end in starts_ends),
            root_cause=root,
            member_findings=tuple(members),
            max_severity=max_severity,
            semantic_importance=importance,
            semantic_position=position,
            evidence=tuple(dict(item.get("evidence") or {}) for item in members),
            cluster_risk=round(primary + bonus, 4),
            recommended_action=action,
            hard_blocker=hard,
        ))
    return sorted(clusters, key=lambda cluster: (cluster.start_ms, cluster.end_ms, cluster.cluster_id))


def language_risk_issue(*, issue_id: str, issue_type: str, timestamp_ms: int = 0,
                        severity: str = "WARNING", semantic_importance: str = "MEDIUM",
                        semantic_position: str = "CONTEXT", evidence_confidence: float = 1.0,
                        evidence: dict[str, Any] | None = None, recommended_action: str = "REVIEW",
                        hard_blocker: bool = False, clip_id: str = "", start_ms: int | None = None,
                        end_ms: int | None = None, root_cause_key: str = "",
                        evidence_source: str = "", semantic_consequence: str = "") -> dict[str, Any]:
    """Build one explainable risk record from objective signals."""
    severity = LanguageIssueSeverity(str(severity).upper()).value
    importance = SemanticImportance(str(semantic_importance).upper()).value
    position = SemanticPosition(str(semantic_position).upper()).value
    confidence = max(0.0, min(1.0, float(evidence_confidence)))
    contribution = (_SEVERITY_WEIGHT[severity] * _IMPORTANCE_WEIGHT[importance]
                    * _POSITION_WEIGHT[position] * confidence)
    start = int(timestamp_ms if start_ms is None else start_ms)
    end = int(start if end_ms is None else end_ms)
    root = root_cause_key or "finding:" + _stable_issue_key((clip_id, issue_id, start, end))
    return {
        "issue_id": issue_id, "timestamp": int(timestamp_ms), "type": issue_type,
        "clip_id": clip_id, "start_ms": start, "end_ms": end,
        "root_cause_key": root, "evidence_source": evidence_source or "same-rule",
        "semantic_consequence": semantic_consequence or issue_type,
        "severity": severity, "semantic_importance": importance,
        "semantic_position": position, "evidence": dict(evidence or {}),
        "evidence_confidence": round(confidence, 4),
        "risk_contribution": round(contribution, 4),
        "recommended_action": recommended_action, "hard_blocker": bool(hard_blocker),
    }


def language_release_state(issues: Iterable[dict[str, Any]], *, timeline_valid: bool = True,
                           untranslated_critical: bool = False) -> tuple[str, float, float]:
    """Return state, aggregate risk, and maximum issue risk."""
    rows = list(issues)
    clusters = cluster_language_issues(rows)
    # Cluster risks are the release units. A family cap remains useful for a
    # long clip with many independent low-impact style findings.
    grouped: dict[str, float] = {}
    for cluster in clusters:
        issue_type = str(cluster.member_findings[0].get("type") or "UNKNOWN")
        grouped[issue_type] = grouped.get(issue_type, 0.0) + cluster.cluster_risk
    total = round(sum(min(value, 3.0) for value in grouped.values()), 4)
    maximum = round(max((cluster.cluster_risk for cluster in clusters), default=0.0), 4)
    blocked = (not timeline_valid or untranslated_critical
               or any(cluster.hard_blocker for cluster in clusters))
    if blocked or maximum >= 5.0 or total >= 9.0:
        return "NEEDS_REVIEW", total, maximum
    if (maximum >= 0.75 or total >= 1.5
            or any(str(item.get("severity")) in {"WARNING", "HIGH"} for item in rows)):
        return "READY_WITH_WARNINGS", total, maximum
    return "READY", total, maximum


@dataclass(frozen=True)
class SubtitleWord:
    word_id: str
    text: str
    start_ms: int
    end_ms: int
    confidence: float | None = None
    language: str = ""
    speaker: str | None = None
    raw_text: str = ""
    source: str = "ASR"
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValueError("SubtitleWord requires recording-relative positive timing")
        if not self.raw_text:
            object.__setattr__(self, "raw_text", self.text)
        object.__setattr__(self, "quality_flags", tuple(dict.fromkeys(self.quality_flags)))


@dataclass
class SubtitleCue:
    cue_id: str
    start_ms: int
    end_ms: int
    source_text: str
    zh_text: str
    en_text: str
    source_language: str
    word_ids: list[str]
    segmentation_reason: str
    confidence: float | None
    translation_status: str
    tone: str = "neutral"
    contains_slang: bool = False
    contains_callback: bool = False
    localization_note: str = ""
    translation_provider: str = ""
    attempt_count: int = 1
    uncertain: bool = False
    tone_preserved: bool = True
    slang_present: bool = False
    profanity_strength: int = 0
    semantic_guard_failures: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class BilingualSubtitleTrack:
    clip_id: str
    source_language: str
    display_mode: BilingualDisplayMode
    cues: list[SubtitleCue]
    translation_provider: str
    timing_provider: str
    translation_mode: TranslationMode = TranslationMode.LOCALIZED_CREATOR
    translation_context_size: int = 7
    translation_release_state: str = "READY"
    timeline_release_state: str = "READY"
    overall_language_quality_state: str = "READY"
    fallback_cue_count: int = 0
    structured_failure_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["display_mode"] = self.display_mode.value
        payload["translation_mode"] = self.translation_mode.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BilingualSubtitleTrack":
        return cls(
            clip_id=str(payload["clip_id"]),
            source_language=str(payload.get("source_language") or ""),
            display_mode=BilingualDisplayMode(str(payload.get("display_mode") or "ZH_EN")),
            cues=[SubtitleCue(**item) for item in payload.get("cues") or []],
            translation_provider=str(payload.get("translation_provider") or "unknown"),
            timing_provider=str(payload.get("timing_provider") or "word_timestamps"),
            translation_mode=TranslationMode(str(payload.get("translation_mode") or "LOCALIZED_CREATOR")),
            translation_context_size=int(payload.get("translation_context_size") or 7),
            translation_release_state=str(payload.get("translation_release_state") or "READY"),
            timeline_release_state=str(payload.get("timeline_release_state") or "READY"),
            overall_language_quality_state=str(payload.get("overall_language_quality_state") or "READY"),
            fallback_cue_count=int(payload.get("fallback_cue_count") or 0),
            structured_failure_count=int(payload.get("structured_failure_count") or 0),
            created_at=str(payload.get("created_at") or datetime.now(timezone.utc).isoformat()),
            schema_version=str(payload.get("schema_version") or "1.0"),
        )


@dataclass(frozen=True)
class ClipLanguageQualityState:
    ASR: str
    Translation: str
    Timeline: str
    Overall: str
    untranslated: int = 0
    timeline_errors: int = 0
    critical_semantic_guard_failures: int = 0
    publishable: bool = False
    human_review: str = "PENDING"

    @property
    def language_quality_ready(self) -> bool:
        return self.Overall == "READY"


@dataclass(frozen=True)
class SegmentationConfig:
    weak_pause_ms: int = 150
    medium_pause_ms: int = 350
    strong_pause_ms: int = 650
    min_duration_ms: int = 600
    target_max_duration_ms: int = 4_000
    soft_max_duration_ms: int = 4_500
    hard_max_duration_ms: int = 6_000
    zh_soft_cps: float = 14.0
    en_soft_cps: float = 21.0


def resolve_scoped_glossary(*, global_terms: dict[str, str] | None = None,
                            creator_terms: dict[str, str] | None = None,
                            game_terms: dict[str, str] | None = None,
                            recording_terms: dict[str, str] | None = None) -> dict[str, str]:
    """Resolve glossary precedence: Recording > Game > Creator > Global."""
    resolved: dict[str, str] = {}
    for terms in (global_terms, creator_terms, game_terms, recording_terms):
        resolved.update(dict(terms or {}))
    return resolved


@dataclass(frozen=True)
class TranslationMemoryEntry:
    source_text: str
    target_text: str
    confirmed: bool = False
    creator_id: str = ""
    game: str = ""


class TranslationMemory:
    """Only explicit user-confirmed translations may influence future output."""

    def __init__(self, entries: Iterable[TranslationMemoryEntry] = ()) -> None:
        self._entries = tuple(entry for entry in entries if entry.confirmed)

    def lookup(self, source_text: str, *, creator_id: str = "", game: str = "") -> str | None:
        for entry in reversed(self._entries):
            if entry.source_text != source_text:
                continue
            if entry.creator_id and entry.creator_id != creator_id:
                continue
            if entry.game and entry.game != game:
                continue
            return entry.target_text
        return None


class TerminologyResolver:
    """Resolve scoped terms only when the source context actually contains the term."""

    def __init__(self, *, global_terms: dict[str, str] | None = None,
                 creator_terms: dict[str, str] | None = None,
                 game_terms: dict[str, str] | None = None,
                 recording_terms: dict[str, str] | None = None) -> None:
        self.terms = resolve_scoped_glossary(
            global_terms=global_terms, creator_terms=creator_terms,
            game_terms=game_terms, recording_terms=recording_terms,
        )

    def applicable(self, source_context: str) -> dict[str, str]:
        lowered = source_context.casefold()
        return {term: value for term, value in self.terms.items()
                if term and term.casefold() in lowered}


class TranslationProvider(Protocol):
    name: str
    model: str

    def translate(self, text: str, *, source_language: str, target_language: str,
                  glossary: dict[str, str]) -> str: ...


class ArgosTranslationProvider:
    name = "argos"
    model = "installed-argos-package"

    def translate(self, text: str, *, source_language: str, target_language: str,
                  glossary: dict[str, str]) -> str:
        from argostranslate import translate

        protected = text
        placeholders: dict[str, str] = {}
        for index, term in enumerate(sorted(glossary, key=len, reverse=True)):
            if term and term in protected:
                token = f"ACFVTERM{index}"
                placeholders[token] = glossary[term] or term
                protected = protected.replace(term, token)
        result = translate.translate(protected, _short_lang(source_language), _short_lang(target_language)).strip()
        for token, value in placeholders.items():
            result = result.replace(token, value)
        if not result:
            raise RuntimeError("Translation provider returned empty text")
        return result


class _StructuredTranslationCue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cue_id: str = Field(min_length=1)
    zh_text: str = Field(min_length=1)
    tone: str = "neutral"
    contains_slang: bool = False
    contains_callback: bool = False
    localization_note: str = ""
    tone_preserved: bool = True
    slang_present: bool = False
    uncertain: bool = False


class _StructuredTranslationGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    translations: list[_StructuredTranslationCue]


class QwenTranslationProvider:
    """Context-preserving local translation through a JSON-capable LLM client."""

    name = "qwen"

    def __init__(self, client: Any, *, model: str = "qwen2.5:7b-instruct") -> None:
        self.client = client
        self.model = model

    def translate(self, text: str, *, source_language: str, target_language: str,
                  glossary: dict[str, str]) -> str:
        if not text.strip():
            raise ValueError("Translation source text is empty")
        payload = self.client.complete_json(
            system_prompt=(
                "Translate creator-video subtitles faithfully. Preserve names, game terms, "
                "slang, profanity, uncertainty, and speaker intent. Do not add facts. "
                "Return one JSON object with a non-empty translation field."
            ),
            user_prompt=(
                f"Source language: {_short_lang(source_language)}\n"
                f"Target language: {_short_lang(target_language)}\n"
                f"Glossary: {json.dumps(glossary, ensure_ascii=False, sort_keys=True)}\n"
                f"Text: {text}"
            ),
            schema={
                "type": "object",
                "properties": {"translation": {"type": "string"}},
                "required": ["translation"],
            },
            validator=self._validate,
            temperature=0.0,
        )
        return str(payload["translation"]).strip()

    def translate_group(self, cues: list[dict[str, str]], *, source_language: str,
                        target_language: str, glossary: dict[str, str],
                        mode: TranslationMode = TranslationMode.LOCALIZED_CREATOR,
                        context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if not cues or any(not item.get("cue_id") or not str(item.get("text") or "").strip() for item in cues):
            raise ValueError("Context translation requires non-empty cue_id/text pairs")
        context = dict(context or {})
        payload = self.client.complete_json(
            system_prompt=(
                "You are translating subtitles for a streamer/video clip. Use the surrounding context to "
                "understand jokes, sarcasm, slang, callbacks, gaming terminology and emotional tone. "
                "Translate naturally into conversational Chinese. Preserve meaning, factual content, profanity "
                "strength, names and game terminology. Do not invent jokes that are absent from the source. "
                "Do not summarize or omit speech. Preserve negation, numbers, questions, named entities and glossary "
                "terms. Do not add unrelated Chinese internet memes. Return exactly one translated entry for every "
                "requested cue_id and no prose outside JSON."
            ),
            user_prompt=(
                f"Mode: {mode.value}\nSource language: {_short_lang(source_language)}\n"
                f"Target language: {_short_lang(target_language)}\n"
                f"Glossary: {json.dumps(glossary, ensure_ascii=False, sort_keys=True)}\n"
                f"Context: {json.dumps(context, ensure_ascii=False, sort_keys=True)}\n"
                f"Cues: {json.dumps(cues, ensure_ascii=False)}"
            ),
            schema={
                "type": "object",
                "properties": {"translations": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "cue_id": {"type": "string"}, "zh_text": {"type": "string"},
                        "tone_preserved": {"type": "boolean"},
                        "slang_present": {"type": "boolean"}, "uncertain": {"type": "boolean"},
                    },
                    "required": ["cue_id", "zh_text", "tone_preserved", "slang_present", "uncertain"],
                }}},
                "required": ["translations"],
            },
            validator=lambda value: self._validate_group(value, cues),
            temperature=0.1 if mode is TranslationMode.LOCALIZED_CREATOR else 0.0,
        )
        rows = [{**row, "attempt_count": int(row.get("attempt_count") or 1)}
                for row in payload["translations"]]
        missing = list(payload.get("missing_cue_ids") or [])
        if missing:
            context = dict(context)
            context["current_semantic_group"] = cues
            by_id = {str(item["cue_id"]): item for item in rows}
            for cue in cues:
                if cue["cue_id"] in missing:
                    repaired = self.translate_group(
                        [cue], source_language=source_language, target_language=target_language,
                        glossary=glossary, mode=mode, context=context,
                    )
                    by_id[cue["cue_id"]] = {**repaired[0], "attempt_count": 2}
            rows = [by_id[cue["cue_id"]] for cue in cues]
        return rows

    @staticmethod
    def _validate(payload: dict[str, Any]) -> dict[str, Any]:
        translated = str(payload.get("translation") or "").strip()
        if not translated:
            raise ValueError("Qwen translation response is empty")
        return {"translation": translated}

    @staticmethod
    def _validate_group(payload: dict[str, Any], cues: list[dict[str, str]]) -> dict[str, Any]:
        expected = [str(item["cue_id"]) for item in cues]
        rows = payload.get("translations")
        if not isinstance(rows, list):
            wrapped = payload.get("translated_entry")
            if isinstance(wrapped, dict):
                rows = [wrapped]
            elif isinstance(wrapped, list):
                rows = wrapped
        if not isinstance(rows, list) and any(cue_id in payload for cue_id in expected):
            rows = []
            for cue_id in expected:
                if cue_id not in payload:
                    continue
                value = payload[cue_id]
                rows.append({"cue_id": cue_id, **value} if isinstance(value, dict)
                            else {"cue_id": cue_id, "text": str(value)})
        if not isinstance(rows, list) and len(cues) == 1:
            legacy_text = str(payload.get("zh_text") or payload.get("translation") or payload.get("text") or "").strip()
            if not legacy_text and str(payload.get("cue_id") or "") == expected[0]:
                legacy_text = str(payload.get("text") or "").strip()
            if legacy_text:
                rows = [{"cue_id": expected[0], "zh_text": legacy_text}]
        if not isinstance(rows, list):
            raise ValueError(f"Qwen contextual response is missing translations: keys={sorted(payload)}")
        by_id: dict[str, dict[str, Any]] = {}
        seen: set[str] = set()
        for item in rows:
            if not isinstance(item, dict):
                continue
            cue_id = str(item.get("cue_id") or "")
            if cue_id in seen:
                raise ValueError(f"Qwen contextual response duplicated cue_id: {cue_id}")
            seen.add(cue_id)
            if cue_id and cue_id not in expected:
                raise ValueError(f"Qwen contextual response returned unexpected cue_id: {cue_id}")
            text = str(item.get("zh_text") or item.get("translation") or item.get("text") or "").strip()
            if cue_id in expected and text and cue_id not in by_id:
                by_id[cue_id] = {
                    "cue_id": cue_id, "zh_text": text,
                    "tone": str(item.get("tone") or "neutral"),
                    "contains_slang": bool(item.get("contains_slang", False)),
                    "contains_callback": bool(item.get("contains_callback", False)),
                    "localization_note": str(item.get("localization_note") or ""),
                    "tone_preserved": bool(item.get("tone_preserved", True)),
                    "slang_present": bool(item.get("slang_present", item.get("contains_slang", False))),
                    "uncertain": bool(item.get("uncertain", False)),
                }
        if not by_id:
            raise ValueError("Qwen contextual response returned no requested cue IDs")
        missing = [cue_id for cue_id in expected if cue_id not in by_id]
        ordered = [by_id[cue_id] for cue_id in expected if cue_id in by_id]
        # The transport schema constrains Ollama; Pydantic independently
        # validates the normalized application payload before it is cached.
        validated = _StructuredTranslationGroup.model_validate({"translations": ordered})
        return {"translations": [item.model_dump() for item in validated.translations],
                "missing_cue_ids": missing}


class FallbackTranslationProvider:
    """Use contextual Qwen first and Argos only after an explicit provider failure."""

    name = "qwen-contextual-with-argos-fallback"

    def __init__(self, primary: TranslationProvider, fallback: TranslationProvider) -> None:
        self.primary = primary
        self.fallback = fallback
        self.model = f"{primary.model}|fallback:{fallback.model}"
        self.last_provider = primary.name

    def translate(self, text: str, **kwargs: Any) -> str:
        try:
            result = self.primary.translate(text, **kwargs)
            self.last_provider = self.primary.name
            return result
        except Exception:
            self.last_provider = self.fallback.name
            return self.fallback.translate(text, **kwargs)

    def translate_group(self, cues: list[dict[str, str]], **kwargs: Any) -> list[dict[str, Any]]:
        contextual = getattr(self.primary, "translate_group", None)
        if callable(contextual):
            context = dict(kwargs.get("context") or {})
            context["current_semantic_group"] = cues
            for attempt in (1, 2):  # initial + one schema repair
                try:
                    rows = contextual(cues, **{**kwargs, "context": context})
                    self.last_provider = self.primary.name
                    return [{**row, "translation_provider": self.primary.name,
                             "attempt_count": max(attempt, int(row.get("attempt_count") or 1))}
                            for row in rows]
                except Exception as exc:
                    context["schema_repair"] = {
                        "attempt": attempt, "instruction": "Return every cue_id exactly once",
                        "prior_error": f"{type(exc).__name__}: {exc}",
                    }
            rows: list[dict[str, Any]] = []
            subgroups = [cues] if len(cues) == 1 else [
                cues[: len(cues) // 2], cues[len(cues) // 2 :]
            ]
            for subgroup in subgroups:
                try:
                    translated = contextual(subgroup, **{**kwargs, "context": {
                        **context, "current_semantic_group": subgroup, "split_retry": True,
                    }})
                    rows.extend({**row, "translation_provider": self.primary.name,
                                 "attempt_count": max(3, int(row.get("attempt_count") or 1))}
                                for row in translated)
                except Exception:
                    rows.extend(self._fallback_row(cue, kwargs, attempt_count=4) for cue in subgroup)
            providers = {row["translation_provider"] for row in rows}
            self.last_provider = next(iter(providers)) if len(providers) == 1 else "MIXED_PROVIDER"
            return rows
        self.last_provider = self.fallback.name
        return [self._fallback_row(item, kwargs, attempt_count=4) for item in cues]

    def _fallback_row(self, item: dict[str, str], kwargs: dict[str, Any], *,
                      attempt_count: int) -> dict[str, Any]:
        return {"cue_id": item["cue_id"], "zh_text": self.fallback.translate(
            item["text"], source_language=kwargs["source_language"],
            target_language=kwargs["target_language"], glossary=kwargs["glossary"],
        ), "tone": "neutral", "contains_slang": False, "contains_callback": False,
            "tone_preserved": False, "slang_present": False, "uncertain": True,
            "localization_note": "argos_provider_fallback",
            "translation_provider": "ARGOS_FALLBACK", "attempt_count": attempt_count}


def default_final_translation_provider(*, timeout: float = 120.0,
                                       max_retries: int = 1) -> FallbackTranslationProvider:
    from acfv.llm.openai_client import OpenAIClientConfig, OpenAIJsonClient

    client = OpenAIJsonClient(OpenAIClientConfig(
        provider="ollama", api_key="ollama", base_url="http://127.0.0.1:11434/v1",
        model="qwen2.5:7b-instruct", timeout=timeout, max_retries=max_retries,
        prefer_responses_api=False,
    ))
    return FallbackTranslationProvider(QwenTranslationProvider(client), ArgosTranslationProvider())


class TranslationCache:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.items: dict[str, str] = {}
        if path and path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.items = {str(key): str(value) for key, value in data.get("items", {}).items()}
            except (OSError, json.JSONDecodeError, AttributeError):
                self.items = {}

    def get_or_translate(self, *, text: str, source_language: str, target_language: str,
                         provider: TranslationProvider, glossary: dict[str, str],
                         glossary_version: str, prompt_version: str) -> str:
        raw = json.dumps({
            "source_text": text,
            "source_language": source_language,
            "target_language": target_language,
            "provider": provider.name,
            "model": provider.model,
            "glossary_version": glossary_version,
            "prompt_version": prompt_version,
        }, sort_keys=True, ensure_ascii=False)
        key = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if key not in self.items:
            self.items[key] = provider.translate(text, source_language=source_language,
                                                 target_language=target_language, glossary=glossary)
            self._save()
        return self.items[key]

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"schema_version": "1.0", "items": self.items},
                                        ensure_ascii=False, indent=2), encoding="utf-8")

    def get_or_translate_group(self, *, cues: list[dict[str, str]], source_language: str,
                               target_language: str, provider: TranslationProvider,
                               glossary: dict[str, str], glossary_version: str,
                               prompt_version: str, mode: TranslationMode,
                               context: dict[str, Any]) -> list[dict[str, Any]]:
        raw = json.dumps({
            "cues": cues, "source_language": source_language, "target_language": target_language,
            "provider": provider.name, "model": provider.model, "glossary": glossary,
            "glossary_version": glossary_version, "prompt_version": prompt_version,
            "translation_mode": mode.value, "context": context,
        }, sort_keys=True, ensure_ascii=False)
        key = "group:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
        cached = self.items.get(key)
        if cached:
            rows = json.loads(cached)
            if isinstance(rows, list):
                return rows
        contextual = getattr(provider, "translate_group", None)
        if callable(contextual):
            rows = contextual(
                cues, source_language=source_language, target_language=target_language,
                glossary=glossary, mode=mode, context=context,
            )
        else:
            rows = [{"cue_id": item["cue_id"], "zh_text": provider.translate(
                item["text"], source_language=source_language,
                target_language=target_language, glossary=glossary,
            )} for item in cues]
        self.items[key] = json.dumps(rows, ensure_ascii=False)
        self._save()
        return rows


_SENTENCE_END = re.compile(r"[.!?。！？][\"'”’)]?$")
_CLAUSE_END = re.compile(r"[,;:，；：][\"'”’)]?$")
_REACTION = re.compile(r"^(?:ah+|oh+|wow|no+|ha+|哈哈+|啊+|呀+|哇+)[!.。！]?+$", re.IGNORECASE)


class BilingualSubtitleService:
    def __init__(self, config: SegmentationConfig | None = None) -> None:
        self.config = config or SegmentationConfig()

    def build_track(
        self,
        *,
        clip_id: str,
        words: Iterable[SubtitleWord],
        clip_start_ms: int,
        clip_end_ms: int,
        source_language: str,
        provider: TranslationProvider,
        display_mode: BilingualDisplayMode = BilingualDisplayMode.ZH_EN,
        completeness: SubtitleCompleteness = SubtitleCompleteness.COMPLETE,
        cache_path: Path | None = None,
        glossary: dict[str, str] | None = None,
        glossary_version: str = "1",
        prompt_version: str = "1",
        timing_provider: str = "faster-whisper-word-timestamps",
        translation_mode: TranslationMode = TranslationMode.LOCALIZED_CREATOR,
        translation_context_size: int = 7,
        translation_context: dict[str, Any] | None = None,
    ) -> BilingualSubtitleTrack:
        if clip_end_ms <= clip_start_ms:
            raise ValueError("Clip end must be after start")
        selected = [word for word in words if word.end_ms > clip_start_ms and word.start_ms < clip_end_ms]
        selected.sort(key=lambda item: (item.start_ms, item.end_ms))
        if not selected:
            raise ValueError("No word timestamps overlap the Clip")
        if selected[0].start_ms < clip_start_ms or selected[-1].end_ms > clip_end_ms:
            raise ValueError("INCOMPLETE_SENTENCE_BOUNDARY: Clip intersects a spoken word")
        groups = self._segment(selected)
        glossary = dict(glossary or {})
        cache = TranslationCache(cache_path)
        drafts: list[dict[str, Any]] = []
        for index, (group, reason) in enumerate(groups, 1):
            source = _join_words(group)
            if completeness is SubtitleCompleteness.CLEAN:
                source = _clean_fillers(source, source_language)
            drafts.append({
                "cue_id": f"{index:04d}", "source": source, "group": group, "reason": reason,
            })
        translations: dict[str, dict[str, Any]] = {}
        language = _short_lang(source_language)
        structured_failures = 0
        if language == "en":
            size = max(5, min(9, int(translation_context_size)))
            try:
                for start_index, batch in _adaptive_translation_batches(drafts, preferred_size=size):
                    context = dict(translation_context or {})
                    context.update({
                        "previous_context": [item["source"] for item in drafts[max(0, start_index - size):start_index]],
                        "current_cues": [{"cue_id": item["cue_id"], "text": item["source"]} for item in batch],
                        "next_context": [item["source"] for item in drafts[start_index + len(batch):start_index + len(batch) + size]],
                    })
                    rows = cache.get_or_translate_group(
                        cues=[{"cue_id": item["cue_id"], "text": item["source"]} for item in batch],
                        source_language="en", target_language="zh", provider=provider, glossary=glossary,
                        glossary_version=glossary_version, prompt_version=prompt_version,
                        mode=translation_mode, context=context,
                    )
                    for row in rows:
                        translations[str(row["cue_id"])] = row
            except Exception as exc:
                raise RuntimeError(f"TRANSLATION_UNAVAILABLE: {exc}") from exc
        cues: list[SubtitleCue] = []
        for draft in drafts:
            source = draft["source"]
            group = draft["group"]
            cue_id = draft["cue_id"]
            metadata: dict[str, Any] = translations.get(cue_id, {})
            if language == "en":
                zh, en = str(metadata.get("zh_text") or "").strip(), source
                if not zh:
                    raise RuntimeError(f"TRANSLATION_UNAVAILABLE: missing contextual translation for {cue_id}")
            else:
                try:
                    zh, en = self._translate_pair(source, source_language, provider, cache, glossary,
                                                  glossary_version, prompt_version)
                except Exception as exc:
                    raise RuntimeError(f"TRANSLATION_UNAVAILABLE: {exc}") from exc
            cue = SubtitleCue(
                cue_id=cue_id,
                start_ms=max(0, group[0].start_ms - clip_start_ms),
                end_ms=min(clip_end_ms, group[-1].end_ms) - clip_start_ms,
                source_text=source,
                zh_text=zh,
                en_text=en,
                source_language=source_language,
                word_ids=[word.word_id for word in group],
                segmentation_reason=draft["reason"],
                confidence=_average_confidence(group),
                translation_status=TranslationRuntimeStatus.READY.value,
                tone=str(metadata.get("tone") or "neutral"),
                contains_slang=bool(metadata.get("contains_slang", False)),
                contains_callback=bool(metadata.get("contains_callback", False)),
                localization_note=str(metadata.get("localization_note") or ""),
                translation_provider=str(metadata.get("translation_provider") or getattr(provider, "name", "unknown")),
                attempt_count=int(metadata.get("attempt_count") or 1),
                uncertain=bool(metadata.get("uncertain", False)),
                tone_preserved=bool(metadata.get("tone_preserved", True)),
                slang_present=bool(metadata.get("slang_present", metadata.get("contains_slang", False))),
                profanity_strength=_profanity_strength(source),
                semantic_guard_failures=translation_semantic_guard(
                    source, zh, glossary=glossary,
                    clip_id=clip_id, cue_id=cue_id,
                    start_ms=max(0, group[0].start_ms - clip_start_ms),
                    end_ms=min(clip_end_ms, group[-1].end_ms) - clip_start_ms,
                    known_creator_entities=(translation_context or {}).get("known_creator_entities", ()),
                    game_terms=(translation_context or {}).get("game_terms", ()),
                    ocr_entities=(translation_context or {}).get("ocr_entities", ()),
                    repeated_high_confidence_entities=(translation_context or {}).get(
                        "repeated_high_confidence_entities", ()
                    ),
                    semantic_position=str((translation_context or {}).get("semantic_position") or "CONTEXT"),
                ),
            )
            cues.append(cue)
        self.validate(cues, clip_end_ms - clip_start_ms, require_bilingual=True)
        providers = {str(item.get("translation_provider") or "") for item in translations.values()}
        providers.discard("")
        if not providers:
            providers = {str(getattr(getattr(provider, "primary", provider), "name", provider.name))}
        normalized_providers = {"ARGOS_FALLBACK" if item.casefold() == "argos" else item for item in providers}
        actual_provider = next(iter(normalized_providers)) if len(normalized_providers) == 1 else "MIXED_PROVIDER"
        fallback_count = sum(cue.translation_provider == "ARGOS_FALLBACK" for cue in cues)
        guard_issues = [failure for cue in cues for failure in cue.semantic_guard_failures]
        critical_failures = sum(bool(failure.get("critical")) for failure in guard_issues)
        fallback_ratio = fallback_count / max(len(cues), 1)
        release_issues = list(guard_issues)
        if fallback_count:
            release_issues.append(language_risk_issue(
                issue_id="translation:provider-fallback", issue_type="PROVIDER_FALLBACK",
                severity="HIGH" if fallback_ratio > 0.20 else "WARNING",
                semantic_importance="HIGH" if fallback_ratio > 0.20 else "LOW",
                evidence={"fallback_count": fallback_count, "fallback_ratio": fallback_ratio},
                hard_blocker=fallback_ratio > 0.20,
            ))
        if any(cue.uncertain for cue in cues):
            release_issues.append(language_risk_issue(
                issue_id="translation:provider-uncertain", issue_type="PROVIDER_UNCERTAIN",
                severity="WARNING", semantic_importance="LOW",
            ))
        translation_state, _, _ = language_release_state(release_issues)
        return BilingualSubtitleTrack(
            clip_id, source_language, display_mode, cues, actual_provider, timing_provider,
            translation_mode, max(5, min(9, int(translation_context_size))),
            translation_release_state=translation_state,
            timeline_release_state="READY",
            overall_language_quality_state=translation_state,
            fallback_cue_count=fallback_count, structured_failure_count=structured_failures,
        )

    def _translate_pair(self, source: str, language: str, provider: TranslationProvider,
                        cache: TranslationCache, glossary: dict[str, str],
                        glossary_version: str, prompt_version: str) -> tuple[str, str]:
        language = _short_lang(language)
        if language == "en":
            en = source
            zh = cache.get_or_translate(text=source, source_language="en", target_language="zh",
                                        provider=provider, glossary=glossary,
                                        glossary_version=glossary_version, prompt_version=prompt_version)
        elif language == "zh":
            zh = source
            en = cache.get_or_translate(text=source, source_language="zh", target_language="en",
                                        provider=provider, glossary=glossary,
                                        glossary_version=glossary_version, prompt_version=prompt_version)
        else:
            zh = cache.get_or_translate(text=source, source_language=language, target_language="zh",
                                        provider=provider, glossary=glossary,
                                        glossary_version=glossary_version, prompt_version=prompt_version)
            en = cache.get_or_translate(text=source, source_language=language, target_language="en",
                                        provider=provider, glossary=glossary,
                                        glossary_version=glossary_version, prompt_version=prompt_version)
        if not zh.strip() or not en.strip():
            raise RuntimeError("TRANSLATION_UNAVAILABLE: bilingual target text is incomplete")
        return zh.strip(), en.strip()

    def _segment(self, words: list[SubtitleWord]) -> list[tuple[list[SubtitleWord], str]]:
        groups: list[tuple[list[SubtitleWord], str]] = []
        current: list[SubtitleWord] = []
        for index, word in enumerate(words):
            current.append(word)
            duration = current[-1].end_ms - current[0].start_ms
            next_word = words[index + 1] if index + 1 < len(words) else None
            gap = (next_word.start_ms - word.end_ms) if next_word else 0
            reason = ""
            if _REACTION.match(_join_words(current)) and duration >= self.config.min_duration_ms:
                reason = "reaction"
            elif _SENTENCE_END.search(word.text) and (gap >= self.config.medium_pause_ms or duration >= self.config.min_duration_ms):
                reason = "sentence_and_pause" if gap >= self.config.medium_pause_ms else "sentence"
            elif _CLAUSE_END.search(word.text) and gap >= self.config.medium_pause_ms:
                reason = "clause_and_pause"
            elif gap >= self.config.strong_pause_ms:
                reason = "strong_pause"
            elif duration >= self.config.hard_max_duration_ms:
                split = self._best_internal_boundary(current)
                if split <= 0:
                    split = max(1, len(current) - 1)
                    split_reason = "hard_max_aligned_word_boundary"
                else:
                    split_reason = "hard_max_semantic_boundary"
                groups.append((current[:split], split_reason))
                current = current[split:]
                continue
            elif duration >= self.config.soft_max_duration_ms and gap >= self.config.weak_pause_ms:
                reason = "soft_max_and_pause"
            if reason and (duration >= self.config.min_duration_ms or reason == "strong_pause"):
                groups.append((current, "short_reaction_or_pause" if duration < self.config.min_duration_ms else reason))
                current = []
        if current:
            if groups and current[-1].end_ms - current[0].start_ms < self.config.min_duration_ms:
                previous, previous_reason = groups[-1]
                combined_duration = current[-1].end_ms - previous[0].start_ms
                if combined_duration <= self.config.hard_max_duration_ms:
                    groups[-1] = (previous + current, previous_reason + "+short_tail")
                else:
                    groups.append((current, "short_reaction_or_tail"))
            else:
                groups.append((current, "clip_end_sentence_boundary"))
        normalized: list[tuple[list[SubtitleWord], str]] = []
        for group, reason in groups:
            pending = list(group)
            while pending and pending[-1].end_ms - pending[0].start_ms > self.config.hard_max_duration_ms:
                split = self._best_internal_boundary(pending)
                if split <= 0 or split >= len(pending):
                    split = max(1, len(pending) - 1)
                    split_reason = "hard_max_aligned_word_boundary"
                else:
                    split_reason = "hard_max_semantic_boundary"
                normalized.append((pending[:split], split_reason))
                pending = pending[split:]
            if pending:
                normalized.append((pending, reason))
        return self._merge_very_short_groups(normalized)

    def _merge_very_short_groups(
        self, groups: list[tuple[list[SubtitleWord], str]]
    ) -> list[tuple[list[SubtitleWord], str]]:
        """Merge only semantically compatible short cues inside real speech bounds."""
        merged: list[tuple[list[SubtitleWord], str]] = []
        index = 0
        while index < len(groups):
            words, reason = groups[index]
            duration = words[-1].end_ms - words[0].start_ms
            if duration >= self.config.min_duration_ms or len(groups) == 1:
                merged.append((words, reason))
                index += 1
                continue
            previous = merged[-1] if merged else None
            following = groups[index + 1] if index + 1 < len(groups) else None
            # A full stop/reaction is an intentional semantic unit. Keep it
            # and report readability rather than silently attaching it.
            standalone = bool(_SENTENCE_END.search(words[-1].text) or _REACTION.match(_join_words(words)))
            if previous and not standalone:
                prior_words, prior_reason = previous
                gap = words[0].start_ms - prior_words[-1].end_ms
                combined = words[-1].end_ms - prior_words[0].start_ms
                if gap <= self.config.medium_pause_ms and combined <= self.config.hard_max_duration_ms:
                    merged[-1] = (prior_words + words, prior_reason + "+merged_short_semantic_cue")
                    index += 1
                    continue
            if following and not standalone:
                next_words, next_reason = following
                gap = next_words[0].start_ms - words[-1].end_ms
                combined = next_words[-1].end_ms - words[0].start_ms
                if gap <= self.config.medium_pause_ms and combined <= self.config.hard_max_duration_ms:
                    groups[index + 1] = (words + next_words, "merged_short_semantic_cue+" + next_reason)
                    index += 1
                    continue
            merged.append((words, reason))
            index += 1
        return merged

    def _best_internal_boundary(self, words: list[SubtitleWord]) -> int:
        candidates: list[tuple[int, int]] = []
        for index in range(1, len(words)):
            previous, following = words[index - 1], words[index]
            gap = following.start_ms - previous.end_ms
            score = gap
            if _SENTENCE_END.search(previous.text):
                score += 2_000
            elif _CLAUSE_END.search(previous.text):
                score += 900
            if previous.end_ms - words[0].start_ms >= self.config.min_duration_ms:
                candidates.append((score, index))
        return max(candidates, default=(-1, 0))[1]

    @staticmethod
    def validate(cues: list[SubtitleCue], clip_duration_ms: int, *, require_bilingual: bool) -> None:
        previous_start = -1
        previous_end = -1
        for cue in cues:
            if cue.start_ms < 0 or cue.end_ms <= cue.start_ms or cue.end_ms > clip_duration_ms:
                raise ValueError(f"Invalid or out-of-range cue: {cue.cue_id}")
            if cue.start_ms < previous_start or cue.start_ms < previous_end:
                raise ValueError(f"Overlapping or non-monotonic cue: {cue.cue_id}")
            if require_bilingual and (not cue.zh_text.strip() or not cue.en_text.strip()):
                raise ValueError(f"Untranslated cue: {cue.cue_id}")
            previous_start, previous_end = cue.start_ms, cue.end_ms

    def write_artifacts(self, track: BilingualSubtitleTrack, output_dir: Path, *,
                        position: SubtitlePosition = SubtitlePosition.AUTO_SAFE_AREA,
                        chinese_size: int = 48, english_size: int = 36,
                        clip_duration_ms: int | None = None,
                        recognized_speech_duration_ms: int | None = None,
                        captioned_speech_duration_ms: int | None = None) -> dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        ass = output_dir / "clip_zh_en.ass"
        srt = output_dir / "clip_zh_en.srt"
        track_path = output_dir / "bilingual_track.json"
        report = output_dir / "subtitle_timeline_report.json"
        _write_srt(track, srt)
        _write_ass(track, ass, position=position, chinese_size=chinese_size, english_size=english_size)
        track_path.write_text(json.dumps(track.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        duration = clip_duration_ms if clip_duration_ms is not None else max(cue.end_ms for cue in track.cues)
        report.write_text(json.dumps(self.quality_report(track, duration,
                                                        recognized_speech_duration_ms=recognized_speech_duration_ms,
                                                        captioned_speech_duration_ms=captioned_speech_duration_ms),
                                     ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ass": ass, "srt": srt, "track": track_path, "report": report}

    @staticmethod
    def load_track(path: Path) -> BilingualSubtitleTrack:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Subtitle track invalid: {exc}") from exc
        track = BilingualSubtitleTrack.from_dict(payload)
        if not track.cues:
            raise ValueError("Subtitle track invalid: no cues")
        return track

    def save_edited_track(self, track: BilingualSubtitleTrack, path: Path, *, clip_duration_ms: int) -> list[str]:
        """Validate and persist user text edits without rebuilding timing or ASS."""
        self.validate(track.cues, clip_duration_ms, require_bilingual=True)
        warnings: list[str] = []
        for cue in track.cues:
            if "\n" in cue.zh_text or "\n" in cue.en_text:
                raise ValueError(f"Cue {cue.cue_id} contains an unsupported line break")
            seconds = max((cue.end_ms - cue.start_ms) / 1000, .001)
            if _zh_chars(cue.zh_text) / seconds > self.config.zh_soft_cps:
                warnings.append(f"{cue.cue_id}: Chinese reading speed exceeds soft limit")
            if _latin_chars(cue.en_text) / seconds > self.config.en_soft_cps:
                warnings.append(f"{cue.cue_id}: English reading speed exceeds soft limit")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(track.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return warnings

    def quality_report(self, track: BilingualSubtitleTrack, clip_duration_ms: int, *,
                       recognized_speech_duration_ms: int | None = None,
                       captioned_speech_duration_ms: int | None = None) -> dict[str, Any]:
        cues = track.cues
        durations = [cue.end_ms - cue.start_ms for cue in cues]
        gaps = [max(0, cues[index].start_ms - cues[index - 1].end_ms) for index in range(1, len(cues))]
        overlaps = sum(cues[index].start_ms < cues[index - 1].end_ms for index in range(1, len(cues)))
        captioned = captioned_speech_duration_ms or sum(durations)
        recognized = recognized_speech_duration_ms or captioned
        zh_cps = [_zh_chars(cue.zh_text) / max((cue.end_ms - cue.start_ms) / 1000, .001) for cue in cues]
        en_cps = [_latin_chars(cue.en_text) / max((cue.end_ms - cue.start_ms) / 1000, .001) for cue in cues]
        guard_failures = [failure for cue in cues for failure in cue.semantic_guard_failures]
        _, guard_risk_total, guard_risk_max = language_release_state(guard_failures)
        readability = []
        for cue, zh_speed, en_speed in zip(cues, zh_cps, en_cps):
            duration = (cue.end_ms - cue.start_ms) / 1000
            if duration < self.config.min_duration_ms / 1000 or zh_speed > 30 or en_speed > 25:
                action = (
                    "MERGED" if "merged_short_semantic_cue" in cue.segmentation_reason
                    else "REFLOWED" if "hard_max" in cue.segmentation_reason
                    else "READABILITY_WARNING"
                )
                readability.append({
                    "cue_id": cue.cue_id, "effective_display_duration": round(duration, 3),
                    "zh_character_count": _zh_chars(cue.zh_text),
                    "en_character_count": _latin_chars(cue.en_text),
                    "zh_cps": round(zh_speed, 3), "en_cps": round(en_speed, 3),
                    "action": action,
                })
        return {
            "schema_version": "1.0",
            "cue_count": len(cues),
            "average_duration_ms": round(sum(durations) / len(durations), 3),
            "min_duration_ms": min(durations),
            "max_duration_ms": max(durations),
            "overlap_count": overlaps,
            "gap_statistics_ms": {"count": len(gaps), "average": round(sum(gaps) / len(gaps), 3) if gaps else 0,
                                  "maximum": max(gaps, default=0)},
            "zh_cps": {"average": round(sum(zh_cps) / len(zh_cps), 3), "maximum": round(max(zh_cps), 3),
                       "over_soft_limit": sum(item > self.config.zh_soft_cps for item in zh_cps)},
            "en_cps": {"average": round(sum(en_cps) / len(en_cps), 3), "maximum": round(max(en_cps), 3),
                       "over_soft_limit": sum(item > self.config.en_soft_cps for item in en_cps)},
            "clipped_cues": 0,
            "out_of_range_cues": sum(cue.start_ms < 0 or cue.end_ms > clip_duration_ms for cue in cues),
            "untranslated_cues": sum(not cue.zh_text.strip() or not cue.en_text.strip() for cue in cues),
            "recognized_speech_duration_ms": recognized,
            "captioned_speech_duration_ms": captioned,
            "coverage": round(min(1.0, captioned / max(recognized, 1)), 4),
            "omitted_items": [],
            "timeline_validity": overlaps == 0 and all(0 <= cue.start_ms < cue.end_ms <= clip_duration_ms for cue in cues),
            "translation_provider": track.translation_provider,
            "translation_release_state": track.translation_release_state,
            "timeline_release_state": track.timeline_release_state,
            "overall_language_quality_state": track.overall_language_quality_state,
            "fallback_cues": track.fallback_cue_count,
            "structured_output_failures": track.structured_failure_count,
            "semantic_guard_failures": guard_failures,
            "critical_semantic_guard_failures": sum(bool(item.get("critical")) for item in guard_failures),
            "semantic_guard_risk_total": guard_risk_total,
            "semantic_guard_risk_max": guard_risk_max,
            "readability_suspects": readability,
            "readability_warning_count": sum(item["action"] == "READABILITY_WARNING" for item in readability),
            "reflowed_cues": sum(item["action"] == "REFLOWED" for item in readability),
            "merged_cues": sum(item["action"] == "MERGED" for item in readability),
        }


def _adaptive_translation_batches(drafts: list[dict[str, Any]], *,
                                  preferred_size: int) -> list[tuple[int, list[dict[str, Any]]]]:
    batches: list[tuple[int, list[dict[str, Any]]]] = []
    index = 0
    while index < len(drafts):
        remaining = drafts[index:]
        reaction_like = all(len(str(item["source"]).split()) <= 4 for item in remaining[:9])
        size = 9 if reaction_like else preferred_size
        while size > 2 and sum(len(str(item["source"])) for item in remaining[:size]) > 900:
            size -= 1
        batch = remaining[:max(1, size)]
        batches.append((index, batch))
        index += len(batch)
    return batches


_EN_NEGATION = re.compile(r"\b(?:not|no|never|cannot|can't|won't|wouldn't|didn't|doesn't|isn't|wasn't|aren't|weren't)\b", re.I)
_ZH_NEGATION = re.compile(r"(?:不|没|沒有|没有|无|無|未|别|別|不能|不会|不會|并非|並非)")
_INVENTED_MEMES = ("笑死", "绷不住", "繃不住", "逆天")
_SOURCE_SLANG = re.compile(r"\b(?:lmao|lol|bro|copium|kekw|pog|based)\b", re.I)
_NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
}
_ZH_NUMBER_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "兩": 2, "三": 3, "四": 4,
                     "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _parse_zh_number(value: str) -> str | None:
    if value == "十":
        return "10"
    if "十" in value:
        left, right = value.split("十", 1)
        tens = _ZH_NUMBER_DIGITS.get(left, 1) if left else 1
        ones = _ZH_NUMBER_DIGITS.get(right, 0) if right else 0
        return str(tens * 10 + ones)
    if len(value) == 1 and value in _ZH_NUMBER_DIGITS:
        return str(_ZH_NUMBER_DIGITS[value])
    return None


def _semantic_numbers(text: str) -> list[str]:
    values = re.findall(r"\d+(?:\.\d+)?%?", text)
    english = re.findall(r"[A-Za-z]+", text)
    for index, token in enumerate(english):
        folded = token.casefold()
        if folded not in _NUMBER_WORDS:
            continue
        if folded == "one" and index and english[index - 1].casefold() in {"no", "some", "any", "every"}:
            continue
        values.append(_NUMBER_WORDS[folded])
    values.extend(parsed for item in re.findall(r"[零一二三四五六七八九十两兩]+", text)
                  if (parsed := _parse_zh_number(item)) is not None)
    return values


def _profanity_strength(text: str) -> int:
    lowered = text.casefold()
    if re.search(r"\b(?:motherfucker|cunt)\b", lowered) or re.search(r"(?:操你|肏你|草你妈|媽的逼)", text):
        return 3
    if re.search(r"\b(?:fuck|fucking|bitch|shit)\b", lowered) or re.search(r"(?:他妈|他媽|操|肏|卧槽|幹你)", text):
        return 2
    if re.search(r"\b(?:damn|hell|ass)\b", lowered) or re.search(r"(?:该死|該死|靠|妈的|媽的)", text):
        return 1
    return 0


def _entity_type(token: str, *, glossary: dict[str, str], known_creator_entities: set[str],
                 game_terms: set[str], ocr_entities: set[str],
                 repeated_high_confidence_entities: set[str]) -> EntityType:
    folded = token.casefold()
    groups = (
        (known_creator_entities, EntityType.KNOWN_CREATOR_ENTITY),
        (game_terms, EntityType.GAME_TERM),
        (ocr_entities, EntityType.OCR_CONFIRMED_ENTITY),
        (set(glossary) | {str(value) for value in glossary.values()}, EntityType.GLOSSARY_ENTITY),
        (repeated_high_confidence_entities, EntityType.REPEATED_HIGH_CONFIDENCE_ENTITY),
    )
    for values, kind in groups:
        if folded in {str(value).casefold() for value in values}:
            return kind
    return EntityType.UNKNOWN_CAPITALIZED_TOKEN


def translation_semantic_guard(source: str, translated: str, *,
                               glossary: dict[str, str] | None = None,
                               known_creator_entities: Iterable[str] = (),
                               game_terms: Iterable[str] = (),
                               ocr_entities: Iterable[str] = (),
                               repeated_high_confidence_entities: Iterable[str] = (),
                               semantic_position: str = "CONTEXT", clip_id: str = "",
                               cue_id: str = "", start_ms: int = 0,
                               end_ms: int | None = None) -> list[dict[str, Any]]:
    """Objective meaning-preservation signals; never a naturalness or humour judge."""
    failures: list[dict[str, Any]] = []

    def add(code: str, *, severity: str, category: str, detail: str = "",
            importance: str = "MEDIUM", hard_blocker: bool = False,
            evidence: dict[str, Any] | None = None) -> None:
        issue = language_risk_issue(
            issue_id=f"translation:{code}:{len(failures) + 1}", issue_type=code,
            clip_id=clip_id, start_ms=start_ms, end_ms=end_ms,
            root_cause_key=f"translation:{clip_id}:{cue_id}:{code}:{detail}",
            evidence_source="translation-semantic-guard", semantic_consequence=code,
            severity=severity, semantic_importance=importance,
            semantic_position=semantic_position, evidence=evidence,
            recommended_action="BLOCK_RELEASE" if hard_blocker else "REVIEW",
            hard_blocker=hard_blocker,
        )
        issue.update({
            "code": code, "category": category,
            "critical": severity == LanguageIssueSeverity.CRITICAL.value,
            "detail": detail,
        })
        failures.append(issue)

    source = source.strip()
    translated = translated.strip()
    if not translated:
        add("CUE_OMISSION", severity="CRITICAL", category="STRUCTURAL",
            importance="CRITICAL", hard_blocker=True)
        return failures
    if _EN_NEGATION.search(source) and not _ZH_NEGATION.search(translated):
        add("NEGATION_MISMATCH", severity="CRITICAL", category="CRITICAL_SEMANTIC",
            importance="CRITICAL", hard_blocker=True)
    source_numbers = _semantic_numbers(source)
    target_numbers = (_semantic_numbers(translated) if source_numbers
                      else re.findall(r"\d+(?:\.\d+)?%?", translated))
    if sorted(source_numbers) != sorted(target_numbers):
        add("NUMBER_MISMATCH", severity="CRITICAL", category="FACTUAL",
            detail=f"{source_numbers!r}->{target_numbers!r}", importance="CRITICAL",
            hard_blocker=True)
    if source.casefold() == translated.casefold() and re.search(r"[A-Za-z]", source):
        tokens = re.findall(r"[A-Za-z0-9_-]+", source)
        legal_label = len(tokens) == 1 and (
            tokens[0].isupper() or tokens[0].casefold() in {
                "twitch", "saruei", "anny", "fms", "cs2",
            }
        )
        if not legal_label:
            add("UNEXPECTED_SOURCE_COPY", severity="HIGH", category="STRUCTURAL",
                importance="HIGH")
    if "?" in source and not re.search(r"[?？]|(?:吗|嗎|呢|怎么|怎麼|为什么|為什麼|谁|誰|什么|什麼)", translated):
        add("QUESTION_FORCE_MISMATCH", severity="WARNING", category="STYLE")
    source_strength = _profanity_strength(source)
    target_strength = _profanity_strength(translated)
    strength_delta = abs(source_strength - target_strength)
    if strength_delta:
        extreme = {source_strength, target_strength} == {0, 3}
        add("PROFANITY_STRENGTH_MISMATCH", severity="HIGH" if extreme else "WARNING",
            category="CRITICAL_SEMANTIC" if extreme else "STYLE",
            detail=f"{source_strength}->{target_strength}", importance="HIGH" if extreme else "LOW")
    if not _SOURCE_SLANG.search(source) and any(item in translated for item in _INVENTED_MEMES):
        add("SUSPICIOUS_INVENTED_MEME", severity="WARNING", category="STYLE", importance="LOW")
    terms = dict(glossary or {})
    for source_term, localized in terms.items():
        if source_term and source_term.casefold() in source.casefold():
            expected = str(localized or source_term)
            if expected.casefold() not in translated.casefold():
                add("GLOSSARY_MISMATCH", severity="HIGH", category="TERMINOLOGY",
                    detail=f"{source_term}->{expected}", importance="HIGH")
    creator_set = {str(item) for item in known_creator_entities}
    game_set = {str(item) for item in game_terms}
    ocr_set = {str(item) for item in ocr_entities}
    repeated_set = {str(item) for item in repeated_high_confidence_entities}
    ordinary_capitalized = {
        "guys", "this", "something", "there", "someone", "everyone", "okay", "no", "yes",
        "i", "the", "a", "an", "what", "why", "how", "when", "where", "who",
        "meet", "hello", "use", "choose", "try", "wait", "pick",
    }
    first_token_start = next((match.start() for match in re.finditer(r"\b[A-Za-z0-9_-]+\b", source)), -1)
    candidates = list(re.finditer(r"\b[A-Z][A-Za-z0-9_-]{1,}\b", source))
    for match in candidates:
        entity = match.group(0)
        if entity.casefold() in ordinary_capitalized:
            continue
        localized = str(terms.get(entity) or entity)
        if entity.casefold() not in translated.casefold() and localized.casefold() not in translated.casefold():
            kind = _entity_type(
                entity, glossary=terms, known_creator_entities=creator_set, game_terms=game_set,
                ocr_entities=ocr_set, repeated_high_confidence_entities=repeated_set,
            )
            if match.start() == first_token_start and kind is EntityType.UNKNOWN_CAPITALIZED_TOKEN:
                continue
            supported = kind is not EntityType.UNKNOWN_CAPITALIZED_TOKEN
            add("ENTITY_MISMATCH", severity="CRITICAL" if supported else "WARNING",
                category="CRITICAL_SEMANTIC" if supported else "STYLE", detail=entity,
                importance="CRITICAL" if supported else "LOW", hard_blocker=supported,
                evidence={"entity_type": kind.value, "capitalization_only": not supported})
    return failures


def _short_lang(language: str) -> str:
    lowered = (language or "").casefold()
    if lowered.startswith(("zh", "chinese")):
        return "zh"
    if lowered.startswith(("en", "english")):
        return "en"
    if lowered.startswith(("ja", "japanese")):
        return "ja"
    return lowered.split("-")[0] or "en"


def _join_words(words: Iterable[SubtitleWord]) -> str:
    parts = [word.text.strip() for word in words if word.text.strip()]
    text = " ".join(parts)
    return re.sub(r"\s+([,.;:!?，。！？；：])", r"\1", text).strip()


def _average_confidence(words: list[SubtitleWord]) -> float | None:
    values = [word.confidence for word in words if word.confidence is not None]
    return round(sum(values) / len(values), 4) if values else None


def _clean_fillers(text: str, language: str) -> str:
    if _short_lang(language) == "en":
        return re.sub(r"\b(?:um+|uh+|erm+)\b[, ]*", "", text, flags=re.IGNORECASE).strip()
    return text.strip()


def _zh_chars(text: str) -> int:
    return len(re.findall(r"[\u3400-\u9fff]", text))


def _latin_chars(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]", text))


def _format_srt(ms: int) -> str:
    hours, rest = divmod(max(0, ms), 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _format_ass(ms: int) -> str:
    total_cs = max(0, int(round(ms / 10)))
    hours, rest = divmod(total_cs, 360_000)
    minutes, rest = divmod(rest, 6_000)
    seconds, centis = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centis:02d}"


def _display_lines(cue: SubtitleCue, mode: BilingualDisplayMode) -> tuple[str, ...]:
    source = cue.source_text
    return {
        BilingualDisplayMode.ZH_EN: (cue.zh_text, cue.en_text),
        BilingualDisplayMode.EN_ZH: (cue.en_text, cue.zh_text),
        BilingualDisplayMode.ZH_ONLY: (cue.zh_text,),
        BilingualDisplayMode.EN_ONLY: (cue.en_text,),
        BilingualDisplayMode.SOURCE_ONLY: (source,),
        BilingualDisplayMode.SOURCE_ZH: (source, cue.zh_text),
        BilingualDisplayMode.SOURCE_EN: (source, cue.en_text),
    }[mode]


def _write_srt(track: BilingualSubtitleTrack, path: Path) -> None:
    lines: list[str] = []
    for index, cue in enumerate(track.cues, 1):
        lines.extend([str(index), f"{_format_srt(cue.start_ms)} --> {_format_srt(cue.end_ms)}",
                      "\n".join(_display_lines(cue, track.display_mode)), ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_ass(track: BilingualSubtitleTrack, path: Path, *, position: SubtitlePosition,
               chinese_size: int, english_size: int) -> None:
    top = position in {SubtitlePosition.TOP, SubtitlePosition.AUTO_SAFE_AREA}
    alignment, margin = (8, 45) if top else (2, 55)
    header = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1920", "PlayResY: 1080", "WrapStyle: 2", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Bilingual,Arial,{chinese_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,{alignment},80,80,{margin},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    events: list[str] = []
    for cue in track.cues:
        lines = _display_lines(cue, track.display_mode)
        if len(lines) == 2:
            first_size = chinese_size if track.display_mode is not BilingualDisplayMode.EN_ZH else english_size
            second_size = english_size if track.display_mode is not BilingualDisplayMode.EN_ZH else chinese_size
            text = rf"{{\fs{first_size}}}{_ass_escape(lines[0])}\N{{\fs{second_size}}}{_ass_escape(lines[1])}"
        else:
            text = rf"{{\fs{chinese_size}}}{_ass_escape(lines[0])}"
        events.append(f"Dialogue: 0,{_format_ass(cue.start_ms)},{_format_ass(cue.end_ms)},Bilingual,,0,0,0,,{text}")
    path.write_text("\n".join(header + events), encoding="utf-8-sig")


def _ass_escape(text: str) -> str:
    return text.replace("{", r"\{").replace("}", r"\}").replace("\n", " ").strip()


def words_from_payload(items: Iterable[dict[str, Any]], *, recording_offset_ms: int = 0,
                       media_start_ms: int = 0, language: str = "") -> list[SubtitleWord]:
    """Normalize ASR seconds onto recording-relative absolute milliseconds."""
    words: list[SubtitleWord] = []
    for index, item in enumerate(items):
        start_value = item.get("start_ms")
        end_value = item.get("end_ms")
        if start_value is None:
            start_value = round(float(item.get("start", 0)) * 1000)
        if end_value is None:
            end_value = round(float(item.get("end", 0)) * 1000)
        start = int(start_value) - media_start_ms + recording_offset_ms
        end = int(end_value) - media_start_ms + recording_offset_ms
        text = str(item.get("word") or item.get("text") or "").strip()
        if text and end > start >= 0:
            words.append(SubtitleWord(
                word_id=str(item.get("word_id") or item.get("id") or f"w{index:06d}"),
                text=text, start_ms=start, end_ms=end,
                confidence=float(item["probability"]) if item.get("probability") is not None else None,
                language=str(item.get("language") or language),
                speaker=str(item["speaker"]) if item.get("speaker") is not None else None,
                raw_text=str(item.get("raw_text") or text),
                source=str(item.get("source") or "ASR"),
                quality_flags=tuple(str(flag) for flag in item.get("quality_flags") or ()),
            ))
    return sorted(words, key=lambda word: (word.start_ms, word.end_ms))


__all__ = ["ArgosTranslationProvider", "FallbackTranslationProvider", "QwenTranslationProvider", "default_final_translation_provider", "BilingualDisplayMode", "BilingualSubtitleService",
           "BilingualSubtitleTrack", "SegmentationConfig", "SubtitleCompleteness", "SubtitleCue",
           "SubtitlePosition", "SubtitleWord", "TerminologyResolver", "TranslationCache",
           "TranslationMemory", "TranslationMemoryEntry", "TranslationMode", "TranslationRuntimeStatus",
           "ClipLanguageQualityState", "resolve_scoped_glossary", "translation_semantic_guard", "words_from_payload"]
