from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class IdentitySource(str, Enum):
    VISUAL = "VISUAL"
    VOICE = "VOICE"
    RECORDING_PRIOR = "RECORDING_PRIOR"
    HUMAN = "HUMAN"


class IdentityState(str, Enum):
    CONFIRMED = "CONFIRMED"
    PROBABLE = "PROBABLE"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


class VisualIdentityLevel(str, Enum):
    STRONG = "VISUAL_STRONG"
    PROBABLE = "VISUAL_PROBABLE"
    AMBIGUOUS = "VISUAL_AMBIGUOUS"
    UNKNOWN = "VISUAL_UNKNOWN"


class TrustLevel(str, Enum):
    RAW = "RAW"
    AUTO_HIGH_CONFIDENCE = "AUTO_HIGH_CONFIDENCE"
    TRUSTED_PSEUDO_LABEL = "TRUSTED_PSEUDO_LABEL"
    HUMAN_CONFIRMED = "HUMAN_CONFIRMED"
    REJECTED = "REJECTED"


class VoiceTrustLevel(str, Enum):
    RAW = "RAW"
    PSEUDO_TRUSTED = "PSEUDO_TRUSTED"
    HUMAN_CONFIRMED = "HUMAN_CONFIRMED"
    REJECTED = "REJECTED"


class LexiconScope(str, Enum):
    GLOBAL = "GLOBAL"
    CREATOR = "CREATOR"
    GAME = "GAME"
    RECORDING = "RECORDING"


class LexiconType(str, Enum):
    COMMON_WORD = "COMMON_WORD"
    PHRASE = "PHRASE"
    CREATOR_CATCHPHRASE = "CREATOR_CATCHPHRASE"
    NAME = "NAME"
    GAME = "GAME"
    CHARACTER = "CHARACTER"
    LOCATION = "LOCATION"
    SKILL = "SKILL"
    TECHNICAL_TERM = "TECHNICAL_TERM"
    OTHER = "OTHER"


class AdaptiveAction(str, Enum):
    KEEP = "KEEP"
    CORRECT = "CORRECT"
    REVIEW = "REVIEW"
    UNCHANGED_UNCERTAIN = "UNCHANGED_UNCERTAIN"
    GENERIC_FALLBACK = "GENERIC_FALLBACK"


@dataclass(frozen=True)
class AvatarIdentityObservation:
    creator_external_id: str
    confidence: float
    timestamp_ms: int
    model_version: str
    provider: str
    frame_quality: float = 1.0
    bbox: tuple[float, float, float, float] | None = None
    track_id: str | None = None
    raw_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VisualIdentitySpan:
    recording_id: str
    start_ms: int
    end_ms: int
    creator_id: str | None
    external_label: str
    level: VisualIdentityLevel
    median_confidence: float
    support_frames: int
    conflict_frames: int
    coverage: float
    model_version: str
    mapping_version: str
    id: str = ""


@dataclass(frozen=True)
class IdentityObservation:
    recording_id: str
    start_ms: int
    end_ms: int
    candidate_creator_id: str
    source: IdentitySource
    confidence: float
    provider: str
    model_version: str
    evidence_ref: str = ""
    raw_metadata: Mapping[str, Any] = field(default_factory=dict)
    id: str = ""


@dataclass(frozen=True)
class CreatorIdentityDecision:
    recording_id: str
    start_ms: int
    end_ms: int
    state: IdentityState
    creator_id: str | None
    visual_score: float = 0.0
    voice_score: float = 0.0
    recording_prior: float = 0.0
    human_evidence: bool = False
    reason: str = ""
    profile_version: str = ""
    evidence_ids: Sequence[str] = ()
    id: str = ""

    @property
    def allows_creator_memory(self) -> bool:
        return self.state in {IdentityState.CONFIRMED, IdentityState.PROBABLE} and bool(self.creator_id)


@dataclass(frozen=True)
class AdaptiveTranscriptDecision:
    recording_id: str
    start_ms: int
    end_ms: int
    generic_text: str
    adaptive_text: str
    action: AdaptiveAction
    creator_id: str | None
    identity_state: IdentityState
    evidence: Mapping[str, Any] = field(default_factory=dict)
    profile_version: str = ""
    id: str = ""

