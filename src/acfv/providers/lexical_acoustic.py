"""Research boundary for lexical acoustic candidate retrieval.

This module intentionally does not edit transcripts.  HuBERT/WavLM adapters may
produce content-sensitive embeddings, while speaker encoders are explicitly
rejected because WHO-similarity is not word-similarity.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Protocol, Sequence


class LexicalAcousticEncoder(Protocol):
    @property
    def model_version(self) -> str: ...

    @property
    def representation_kind(self) -> str: ...

    def encode(self, audio_path: str, start_ms: int, end_ms: int) -> Sequence[float]: ...


@dataclass(frozen=True)
class LexicalAcousticExemplar:
    creator_id: str
    normalized_text: str
    recording_id: str
    start_ms: int
    end_ms: int
    embedding: tuple[float, ...]
    profile_version: str
    voice_mode: str = ""
    split_role: str = "TRAIN"


@dataclass(frozen=True)
class LexicalAcousticCandidate:
    text: str
    score: float
    exemplar_recording_id: str
    voice_mode: str
    model_version: str
    evidence_only: bool = True


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or len(left) != len(right):
        raise ValueError("lexical acoustic vectors must have equal non-zero dimensions")
    denominator = math.sqrt(sum(x * x for x in left) * sum(x * x for x in right))
    return sum(x * y for x, y in zip(left, right)) / denominator if denominator else 0.0


class LexicalAcousticMemory:
    """Creator-scoped nearest-exemplar research index returning candidates only."""

    ALLOWED_REPRESENTATIONS = frozenset({"LEXICAL_HUBERT", "LEXICAL_WAVLM"})

    def __init__(self, encoder: LexicalAcousticEncoder, exemplars: Iterable[LexicalAcousticExemplar]) -> None:
        if encoder.representation_kind not in self.ALLOWED_REPRESENTATIONS:
            raise ValueError("speaker identity embeddings cannot be used as lexical acoustic memory")
        self.encoder = encoder
        self.exemplars = tuple(exemplars)
        if any(row.split_role != "TRAIN" for row in self.exemplars):
            raise ValueError("lexical acoustic exemplars must come from frozen TRAIN VODs")

    def query(
        self, *, creator_id: str, profile_version: str, audio_path: str,
        start_ms: int, end_ms: int, voice_mode: str = "", limit: int = 5,
    ) -> tuple[LexicalAcousticCandidate, ...]:
        query = tuple(float(value) for value in self.encoder.encode(audio_path, start_ms, end_ms))
        scoped = [
            row for row in self.exemplars
            if row.creator_id == creator_id and row.profile_version == profile_version
        ]
        ranked: list[tuple[float, LexicalAcousticExemplar]] = []
        for row in scoped:
            score = _cosine(query, row.embedding)
            if voice_mode and row.voice_mode == voice_mode:
                score += 0.01  # bounded tie-break only; sparse modes never hide other evidence
            ranked.append((score, row))
        ranked.sort(key=lambda item: (-item[0], item[1].normalized_text, item[1].recording_id))
        return tuple(
            LexicalAcousticCandidate(
                text=row.normalized_text,
                score=min(1.0, score),
                exemplar_recording_id=row.recording_id,
                voice_mode=row.voice_mode,
                model_version=self.encoder.model_version,
            )
            for score, row in ranked[:max(0, int(limit))]
        )
