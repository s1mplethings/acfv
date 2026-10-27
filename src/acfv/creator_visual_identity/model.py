from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

import numpy as np
from sklearn.cluster import KMeans
from sklearn.linear_model import LogisticRegression


class VisualIdentityState(str, Enum):
    STRONG = "STRONG"
    PROBABLE = "PROBABLE"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class IdentityPrediction:
    creator_id: str | None
    state: VisualIdentityState
    score: float
    margin: float
    second_creator_id: str | None
    prototype_id: str
    model_version: str
    support_score: float = 1.0


class VisualEncoder(Protocol):
    @property
    def model_version(self) -> str: ...
    def encode(self, images: Iterable[Any]) -> np.ndarray: ...


class PrototypeIdentityModel:
    def __init__(
        self, *, model_version: str, strong_score: float, strong_margin: float,
        probable_score: float, probable_margin: float, prototypes: Mapping[str, np.ndarray],
    ) -> None:
        self.model_version = model_version
        self.strong_score = float(strong_score)
        self.strong_margin = float(strong_margin)
        self.probable_score = float(probable_score)
        self.probable_margin = float(probable_margin)
        self.prototypes = {str(key): self._normalize(np.asarray(value, dtype=np.float32)) for key, value in prototypes.items()}
        if len(self.prototypes) < 2:
            raise ValueError("at least two Creator prototype sets are required")

    @staticmethod
    def _normalize(values: np.ndarray) -> np.ndarray:
        if values.ndim == 1:
            values = values[None, :]
        norms = np.linalg.norm(values, axis=1, keepdims=True)
        if np.any(norms <= 1e-12):
            raise ValueError("zero-length identity embedding")
        return values / norms

    @classmethod
    def fit(
        cls, embeddings: np.ndarray, labels: Iterable[str], *, encoder_version: str,
        prototypes_per_creator: int = 4, strong_score: float = .75, strong_margin: float = .08,
        probable_score: float = .60, probable_margin: float = .03,
    ) -> "PrototypeIdentityModel":
        vectors = cls._normalize(np.asarray(embeddings, dtype=np.float32))
        label_rows = np.asarray(list(labels))
        if len(vectors) != len(label_rows):
            raise ValueError("embedding/label length mismatch")
        prototypes: dict[str, np.ndarray] = {}
        for creator in sorted(set(str(value) for value in label_rows)):
            rows = vectors[label_rows == creator]
            count = min(prototypes_per_creator, len(rows))
            if count == 0:
                continue
            if count == 1:
                prototypes[creator] = rows
                continue
            cluster = KMeans(n_clusters=count, random_state=0, n_init=10).fit(rows)
            medoids = []
            for center in cluster.cluster_centers_:
                medoids.append(rows[int(np.argmax(rows @ cls._normalize(center)[0]))])
            prototypes[creator] = np.stack(medoids)
        return cls(
            model_version=f"{encoder_version}-prototype-v1", strong_score=strong_score,
            strong_margin=strong_margin, probable_score=probable_score,
            probable_margin=probable_margin, prototypes=prototypes,
        )

    def predict(self, embedding: np.ndarray) -> IdentityPrediction:
        vector = self._normalize(np.asarray(embedding, dtype=np.float32))[0]
        ranked: list[tuple[float, str, int]] = []
        for creator, prototypes in self.prototypes.items():
            scores = prototypes @ vector
            index = int(np.argmax(scores))
            ranked.append((float(scores[index]), creator, index))
        ranked.sort(reverse=True)
        top, second = ranked[0], ranked[1]
        margin = top[0] - second[0]
        if top[0] >= self.strong_score and margin >= self.strong_margin:
            state, creator = VisualIdentityState.STRONG, top[1]
        elif top[0] >= self.probable_score and margin >= self.probable_margin:
            state, creator = VisualIdentityState.PROBABLE, top[1]
        elif top[0] >= self.probable_score:
            state, creator = VisualIdentityState.AMBIGUOUS, None
        else:
            state, creator = VisualIdentityState.UNKNOWN, None
        return IdentityPrediction(creator, state, top[0], margin, second[1], f"{top[1]}:{top[2]}", self.model_version)

    def save(self, path: Path) -> Path:
        payload = {
            "schema_version": 1, "model_version": self.model_version,
            "strong_score": self.strong_score, "strong_margin": self.strong_margin,
            "probable_score": self.probable_score, "probable_margin": self.probable_margin,
            "prototypes": {key: value.tolist() for key, value in self.prototypes.items()},
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "PrototypeIdentityModel":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            model_version=payload["model_version"], strong_score=payload["strong_score"],
            strong_margin=payload["strong_margin"], probable_score=payload["probable_score"],
            probable_margin=payload["probable_margin"],
            prototypes={key: np.asarray(value, dtype=np.float32) for key, value in payload["prototypes"].items()},
        )


class CreatorVisualIdentityService:
    def __init__(self, encoder: VisualEncoder, model: PrototypeIdentityModel) -> None:
        self.encoder = encoder
        self.model = model

    def identify_crops(self, crops: Iterable[Any]) -> list[IdentityPrediction]:
        vectors = self.encoder.encode(list(crops))
        return [self.model.predict(vector) for vector in vectors]


class LinearProbeIdentityModel:
    """Frozen-backbone linear probe with explicit open-set rejection."""

    def __init__(self, classifier: LogisticRegression, *, encoder_version: str, strong_score: float, strong_margin: float, probable_score: float, probable_margin: float, support_prototypes: Mapping[str, np.ndarray], min_support: float = .75) -> None:
        self.classifier = classifier
        self.model_version = f"{encoder_version}-linear-probe-v1"
        self.strong_score = strong_score
        self.strong_margin = strong_margin
        self.probable_score = probable_score
        self.probable_margin = probable_margin
        self.support_prototypes = {str(key): PrototypeIdentityModel._normalize(value)[0] for key, value in support_prototypes.items()}
        self.min_support = float(min_support)

    @classmethod
    def fit(cls, embeddings: np.ndarray, labels: Iterable[str], *, encoder_version: str, strong_score: float = .90, strong_margin: float = .25, probable_score: float = .70, probable_margin: float = .10) -> "LinearProbeIdentityModel":
        vectors = PrototypeIdentityModel._normalize(np.asarray(embeddings, dtype=np.float32))
        label_rows = np.asarray(list(labels))
        classifier = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=0).fit(vectors, label_rows)
        support = {str(creator): vectors[label_rows == creator].mean(axis=0) for creator in classifier.classes_}
        return cls(classifier, encoder_version=encoder_version, strong_score=strong_score, strong_margin=strong_margin, probable_score=probable_score, probable_margin=probable_margin, support_prototypes=support)

    def predict(self, embedding: np.ndarray) -> IdentityPrediction:
        vector = PrototypeIdentityModel._normalize(np.asarray(embedding, dtype=np.float32))
        probabilities = self.classifier.predict_proba(vector)[0]
        order = np.argsort(probabilities)[::-1]
        top, second = int(order[0]), int(order[1])
        score, margin = float(probabilities[top]), float(probabilities[top] - probabilities[second])
        creator = str(self.classifier.classes_[top])
        support = float(vector[0] @ self.support_prototypes[creator])
        if support < self.min_support:
            state, selected = VisualIdentityState.UNKNOWN, None
        elif score >= self.strong_score and margin >= self.strong_margin:
            state, selected = VisualIdentityState.STRONG, creator
        elif score >= self.probable_score and margin >= self.probable_margin:
            state, selected = VisualIdentityState.PROBABLE, creator
        elif score >= self.probable_score:
            state, selected = VisualIdentityState.AMBIGUOUS, None
        else:
            state, selected = VisualIdentityState.UNKNOWN, None
        return IdentityPrediction(selected, state, score, margin, str(self.classifier.classes_[second]), f"linear:{top}", self.model_version, support)

    def save(self, path: Path) -> Path:
        import joblib
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)
        return path

    @classmethod
    def load(cls, path: Path) -> "LinearProbeIdentityModel":
        import joblib
        value = joblib.load(path)
        if not isinstance(value, cls):
            raise TypeError("linear identity artifact has the wrong type")
        return value
