from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

from acfv.library.models import IndexStatus
from acfv.library.repository import LibraryRepository
from acfv.library.artifacts import resolve_artifact_root
from acfv.moments.models import Moment, MomentStatus
from acfv.ragstack.embeddings.encoder import DEFAULT_EMBEDDING_MODEL, config_hash, load_encoder, runtime_info
from acfv.ragstack.index.faiss_index import build_index, search
from acfv.runtime.storage import storage_root


@dataclass(frozen=True)
class IndexedMoment:
    moment_id: str
    creator_id: str
    recording_id: str
    start_ms: int
    end_ms: int
    status: str
    recorded_at: str | None
    search_text: str
    summary: str


@dataclass(frozen=True)
class IndexedRepresentation:
    row_id: int
    representation_id: str
    parent_moment_id: str
    creator_id: str
    recording_id: str
    start_ms: int
    end_ms: int
    representation_type: str
    text: str


@dataclass(frozen=True)
class SemanticHit:
    moment_id: str
    score: float
    representation_id: str
    representation_type: str
    excerpt: str
    start_ms: int
    end_ms: int
    representation_rank: int
    second_hit_score: float | None = None


class PersistentMomentIndex:
    VERSION = 5
    REPRESENTATION_SCHEMA = "moment-representations-v2"
    PASSAGE_MIN_TOKENS = 100
    PASSAGE_TARGET_TOKENS = 180
    PASSAGE_MAX_TOKENS = 250
    PASSAGE_MAX_UNITS = 6
    PASSAGE_OVERLAP_UNITS = 1
    SECOND_HIT_BONUS = 0.02
    CONTEXT_QUERY = re.compile(r"\b(?:before|after|earlier|later|previous|next)\b|之前|之后|此前|后来|前面|后面", re.IGNORECASE)

    def __init__(self, repository: LibraryRepository, index_root: Path | None = None, *, encoder: Callable[[Iterable[str]], np.ndarray] | None = None, model_name: str = DEFAULT_EMBEDDING_MODEL, reuse_root: Path | None = None) -> None:
        self.repository = repository
        self.root = Path(index_root or storage_root() / "moment_index")
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "moments.faiss"
        self.id_map_path = self.root / "row_ids.npy"
        self.embedding_path = self.root / "embeddings.npy"
        self.manifest_path = self.root / "manifest.json"
        self.encoder = encoder
        self.model_name = model_name
        self.reuse_root = Path(reuse_root) if reuse_root else None
        self._quality_span_cache: dict[str, list[dict]] = {}

    def rebuild(self) -> int:
        moments = self.repository.list_moments()
        recording_ids = {moment.recording_id for moment in moments}
        for recording_id in recording_ids:
            recording = self.repository.get_recording(recording_id)
            if recording:
                recording.index_status = IndexStatus.INDEXING
                self.repository.save(recording)
        by_recording: dict[str, list[Moment]] = {}
        for moment in moments:
            by_recording.setdefault(moment.recording_id, []).append(moment)
        parents = [self._parent(moment) for moment in moments]
        representations: list[IndexedRepresentation] = []
        for recording_moments in by_recording.values():
            ordered = sorted(recording_moments, key=lambda item: (item.start_ms, item.end_ms))
            for position, moment in enumerate(ordered):
                previous = ordered[position - 1] if position else None
                following = ordered[position + 1] if position + 1 < len(ordered) else None
                quality_spans = self._quality_spans(moment.recording_id, moment.start_ms, moment.end_ms)
                for representation in self._representations(moment, previous, following, quality_spans=quality_spans):
                    representations.append(IndexedRepresentation(row_id=len(representations), **representation))
        representations = [
            replace(row, row_id=row_id)
            for row_id, row in enumerate(sorted(representations, key=lambda item: (len(item.text), item.representation_id)))
        ]
        dimension = None
        reuse_stats = {"reused": 0, "encoded": len(representations)}
        if representations:
            embeddings, reuse_stats = self._encode_reusing(representations)
            dimension = int(embeddings.shape[1])
            build_index(embeddings, [row.row_id for row in representations], self.index_path, self.id_map_path, emb_cache_path=self.embedding_path)
        info = runtime_info(self._encoder(), self.model_name)
        dimension = dimension or info.dimension
        representation_config = self._representation_config()
        payload = {
            "version": self.VERSION,
            "embedding_model": self.model_name,
            "embedding_dimension": dimension,
            "embedding_backend": info.backend,
            "embedding_mode": info.mode.value,
            "embedding_version": config_hash(self.model_name, dimension, info.backend),
            "representation_schema": self.REPRESENTATION_SCHEMA,
            "representation_config": representation_config,
            "representation_config_hash": self._representation_config_hash(representation_config),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "parents": [asdict(row) for row in parents],
            "representations": [asdict(row) for row in representations],
            "embedding_reuse": reuse_stats,
        }
        temporary = self.manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.manifest_path)
        for recording_id in recording_ids:
            recording = self.repository.get_recording(recording_id)
            if recording:
                recording.index_status = IndexStatus.READY
                self.repository.save(recording)
        return len(parents)

    def _encode_reusing(self, representations: list[IndexedRepresentation]) -> tuple[np.ndarray, dict[str, int]]:
        if self.reuse_root is None:
            values = self._encode([row.text for row in representations], query=False)
            return values, {"reused": 0, "encoded": len(representations)}
        manifest_path = self.reuse_root / "manifest.json"
        embeddings_path = self.reuse_root / "embeddings.npy"
        if not manifest_path.is_file() or not embeddings_path.is_file():
            values = self._encode([row.text for row in representations], query=False)
            return values, {"reused": 0, "encoded": len(representations)}
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            previous_embeddings = np.load(embeddings_path)
        except (OSError, ValueError, json.JSONDecodeError):
            values = self._encode([row.text for row in representations], query=False)
            return values, {"reused": 0, "encoded": len(representations)}
        if previous.get("embedding_model") != self.model_name or previous_embeddings.ndim != 2:
            values = self._encode([row.text for row in representations], query=False)
            return values, {"reused": 0, "encoded": len(representations)}
        prior_rows = {
            str(item.get("representation_id")): item
            for item in previous.get("representations", [])
            if isinstance(item, dict)
        }
        output = np.empty((len(representations), previous_embeddings.shape[1]), dtype=np.float32)
        missing_indices: list[int] = []
        missing_texts: list[str] = []
        reused = 0
        for index, row in enumerate(representations):
            prior = prior_rows.get(row.representation_id)
            prior_row_id = int(prior.get("row_id", -1)) if prior else -1
            if prior and prior.get("text") == row.text and 0 <= prior_row_id < len(previous_embeddings):
                output[index] = previous_embeddings[prior_row_id]
                reused += 1
            else:
                missing_indices.append(index)
                missing_texts.append(row.text)
        if missing_texts:
            encoded = self._encode(missing_texts, query=False)
            if encoded.shape[1] != output.shape[1]:
                raise RuntimeError("Reusable index embedding dimension does not match the active encoder")
            output[missing_indices] = encoded
        return output, {"reused": reused, "encoded": len(missing_indices)}

    def search(self, query: str, *, top_k: int = 10, creator_id: str | None = None, recording_id: str | None = None, representation_types: set[str] | None = None) -> list[SemanticHit]:
        representations = self.representations()
        if not representations or not query.strip():
            return []
        requested = len(representations) if representation_types else min(len(representations), max(top_k * 4, top_k))
        row_ids, scores = search(self._encode([query], query=True), requested, self.index_path, self.id_map_path, emb_cache_path=self.embedding_path)
        row_map = {row.row_id: row for row in representations}
        by_parent: dict[str, list[tuple[int, float, IndexedRepresentation]]] = {}
        for rank, (row_id, score) in enumerate(zip(row_ids, scores), 1):
            row = row_map.get(row_id)
            if row is None or (representation_types and row.representation_type not in representation_types) or (creator_id and row.creator_id != creator_id) or (recording_id and row.recording_id != recording_id):
                continue
            by_parent.setdefault(row.parent_moment_id, []).append((rank, float(score), row))
        hits: list[SemanticHit] = []
        for moment_id, parent_hits in by_parent.items():
            parent_hits.sort(key=lambda item: item[1], reverse=True)
            best_rank, best_score, best_row = parent_hits[0]
            if self.CONTEXT_QUERY.search(query):
                rank, _, row = next(
                    (item for item in parent_hits if item[2].representation_type == "NEIGHBOR_CONTEXT" and item[1] >= best_score - 0.04),
                    (best_rank, best_score, best_row),
                )
            else:
                rank, _, row = next(
                    (item for item in parent_hits if item[2].representation_type != "NEIGHBOR_CONTEXT" and item[1] >= best_score - 0.01),
                    (best_rank, best_score, best_row),
                )
            second = parent_hits[1][1] if len(parent_hits) > 1 else None
            aggregate = best_score + (self.SECOND_HIT_BONUS * max(0.0, second) if second is not None else 0.0)
            hits.append(SemanticHit(moment_id, aggregate, row.representation_id, row.representation_type, row.text[:500], row.start_ms, row.end_ms, rank, second))
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[:top_k]

    def rows(self) -> list[IndexedMoment]:
        return [IndexedMoment(**item) for item in self._manifest().get("parents", [])]

    def representations(self) -> list[IndexedRepresentation]:
        return [IndexedRepresentation(**item) for item in self._manifest().get("representations", [])]

    def _encoder(self):
        if self.encoder is None:
            os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
            self.encoder = load_encoder(self.model_name)
        return self.encoder

    def _encode(self, texts: Iterable[str], *, query: bool) -> np.ndarray:
        encoder = self._encoder()
        method = getattr(encoder, "encode_queries" if query else "encode_passages", None)
        return method(texts) if method else encoder(texts)

    def runtime_metadata(self) -> dict:
        info = runtime_info(self._encoder(), self.model_name)
        manifest = self._manifest()
        return {"embedding_backend": info.backend, "embedding_model": info.model, "embedding_dimension": info.dimension, "embedding_device": info.device, "retrieval_mode": info.mode.value, "index_version": manifest.get("version"), "representation_schema": manifest.get("representation_schema"), "parent_moments": len(manifest.get("parents", [])), "representations": len(manifest.get("representations", []))}

    def _manifest(self) -> dict:
        if not self.manifest_path.is_file():
            return {"version": self.VERSION, "parents": [], "representations": []}
        payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if payload.get("version") != self.VERSION:
            raise RuntimeError("Moment index version is not supported; rebuild the retrieval index")
        if payload.get("representation_config_hash") != self._representation_config_hash(self._representation_config()):
            raise RuntimeError("Moment representation configuration changed; rebuild the retrieval index")
        if payload.get("representations") and payload.get("embedding_model") != self.model_name:
            raise RuntimeError("Moment index embedding model changed; rebuild the retrieval index")
        if payload.get("representations"):
            info = runtime_info(self._encoder(), self.model_name)
            expected = config_hash(self.model_name, payload.get("embedding_dimension"), info.backend)
            if payload.get("embedding_version") != expected:
                raise RuntimeError("Moment index embedding configuration changed; rebuild the retrieval index")
        return payload

    @classmethod
    def _representation_config(cls) -> dict:
        return {"passage_min_tokens": cls.PASSAGE_MIN_TOKENS, "passage_target_tokens": cls.PASSAGE_TARGET_TOKENS, "passage_max_tokens": cls.PASSAGE_MAX_TOKENS, "passage_max_units": cls.PASSAGE_MAX_UNITS, "passage_overlap_units": cls.PASSAGE_OVERLAP_UNITS, "second_hit_bonus": cls.SECOND_HIT_BONUS}

    @staticmethod
    def _representation_config_hash(payload: dict) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    @staticmethod
    def _parent(moment: Moment) -> IndexedMoment:
        fields, seen = [], set()
        for value in (moment.summary, moment.transcript_text, moment.ocr_text, moment.chat_text, moment.visual_text):
            compact = " ".join((value or "").split())
            if compact and compact.casefold() not in seen:
                fields.append(compact)
                seen.add(compact.casefold())
        return IndexedMoment(moment.id, moment.creator_id, moment.recording_id, moment.start_ms, moment.end_ms, moment.status.value, moment.created_at.isoformat() if moment.created_at else None, "\n".join(fields), moment.summary)

    @classmethod
    def _row(cls, _row_id: int, moment: Moment, context: Iterable[str] = ()) -> IndexedMoment:
        """Compatibility view for callers that inspect the legacy combined text."""
        parent = cls._parent(moment)
        fields = parent.search_text.splitlines()
        seen = {item.casefold() for item in fields}
        for value in context:
            compact = " ".join((value or "").split())
            if compact and compact.casefold() not in seen:
                fields.append(compact)
                seen.add(compact.casefold())
        return replace(parent, search_text="\n".join(fields))

    @classmethod
    def _representations(cls, moment: Moment, previous: Moment | None, following: Moment | None, *, quality_spans: list[dict] | None = None) -> list[dict]:
        common = {"parent_moment_id": moment.id, "creator_id": moment.creator_id, "recording_id": moment.recording_id}
        rows: list[dict] = []

        def add(kind: str, index: int, text: str, start_ms: int, end_ms: int) -> None:
            compact = " ".join((text or "").split())
            if compact:
                rows.append({**common, "representation_id": f"{moment.id}:{kind.lower()}:{index}", "start_ms": int(start_ms), "end_ms": int(end_ms), "representation_type": kind, "text": compact})

        add("SUMMARY", 0, moment.summary, moment.start_ms, moment.end_ms)
        add("FULL_TRANSCRIPT", 0, moment.transcript_text, moment.start_ms, moment.end_ms)
        if quality_spans:
            speech = [
                item for item in quality_spans
                if item.get("classification") in {"SPEECH", "NON_SPEECH_REACTION"}
            ]
            lyrics = [item for item in quality_spans if item.get("classification") == "LIKELY_BACKGROUND_LYRICS"]
            if speech:
                add(
                    "CORRECTED_SPEECH", 0,
                    " ".join(str(item.get("display_text") or "") for item in speech),
                    int(speech[0].get("start_ms", moment.start_ms)),
                    int(speech[-1].get("end_ms", moment.end_ms)),
                )
            if lyrics:
                add(
                    "BACKGROUND_LYRICS", 0,
                    " ".join(str(item.get("display_text") or "") for item in lyrics),
                    int(lyrics[0].get("start_ms", moment.start_ms)),
                    int(lyrics[-1].get("end_ms", moment.end_ms)),
                )
        if moment.status == MomentStatus.FINAL:
            for index, passage in enumerate(cls._passages(moment)):
                add("PASSAGE", index, passage["text"], passage["start_ms"], passage["end_ms"])
            context = []
            if previous:
                context.append(cls._tail(previous.transcript_text, 80))
            context.append(moment.summary or cls._head(moment.transcript_text, 100))
            if following:
                context.append(cls._head(following.transcript_text, 80))
            add("NEIGHBOR_CONTEXT", 0, " ".join(context), moment.start_ms, moment.end_ms)
        if not rows:
            add("SUMMARY", 0, moment.title, moment.start_ms, moment.end_ms)
        return rows

    def _quality_spans(self, recording_id: str, start_ms: int, end_ms: int) -> list[dict]:
        if recording_id not in self._quality_span_cache:
            recording = self.repository.get_recording(recording_id)
            root = resolve_artifact_root(recording) if recording is not None else None
            path = root / "work" / "transcript_quality.json" if root else None
            if path and path.is_file():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    self._quality_span_cache[recording_id] = [item for item in payload.get("spans", []) if isinstance(item, dict)]
                except (json.JSONDecodeError, OSError):
                    self._quality_span_cache[recording_id] = []
            else:
                self._quality_span_cache[recording_id] = []
        return [
            item for item in self._quality_span_cache[recording_id]
            if int(item.get("end_ms", 0)) > start_ms and int(item.get("start_ms", 0)) < end_ms
        ]

    @classmethod
    def _passages(cls, moment: Moment) -> list[dict]:
        units = cls._transcript_units(moment)
        passages, start = [], 0
        while start < len(units):
            end, tokens = start, 0
            while end < len(units) and end - start < cls.PASSAGE_MAX_UNITS:
                count = cls._token_count(units[end]["text"])
                if end > start and tokens >= cls.PASSAGE_MIN_TOKENS and tokens + count > cls.PASSAGE_TARGET_TOKENS:
                    break
                if end > start and tokens + count > cls.PASSAGE_MAX_TOKENS:
                    break
                tokens += count
                end += 1
            if end == start:
                end += 1
            selected = units[start:end]
            passages.append({"text": " ".join(item["text"] for item in selected), "start_ms": selected[0]["start_ms"], "end_ms": selected[-1]["end_ms"]})
            if end >= len(units):
                break
            start = max(start + 1, end - cls.PASSAGE_OVERLAP_UNITS)
        return passages

    @staticmethod
    def _transcript_units(moment: Moment) -> list[dict]:
        try:
            evidence = json.loads(moment.evidence_json)
        except (json.JSONDecodeError, TypeError):
            evidence = []
        units = [{"text": " ".join(str(item.get("text") or "").split()), "start_ms": int(item.get("start_ms", moment.start_ms)), "end_ms": int(item.get("end_ms", moment.end_ms))} for item in evidence if isinstance(item, dict) and item.get("type") == "transcript" and str(item.get("text") or "").strip()]
        if units:
            return units
        sentences = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", moment.transcript_text) if part.strip()]
        if not sentences and moment.transcript_text.strip():
            sentences = [moment.transcript_text.strip()]
        duration, total, cursor = max(1, moment.end_ms - moment.start_ms), max(1, sum(len(item) for item in sentences)), moment.start_ms
        fallback = []
        for index, sentence in enumerate(sentences):
            end = moment.end_ms if index + 1 == len(sentences) else cursor + round(duration * len(sentence) / total)
            fallback.append({"text": sentence, "start_ms": cursor, "end_ms": end})
            cursor = end
        return fallback

    @staticmethod
    def _token_count(text: str) -> int:
        return len(re.findall(r"[A-Za-z0-9]+|[\u3400-\u9fff]|[\u3040-\u30ff]+", text))

    @staticmethod
    def _head(text: str, tokens: int) -> str:
        return " ".join(text.split()[:tokens])

    @staticmethod
    def _tail(text: str, tokens: int) -> str:
        return " ".join(text.split()[-tokens:])
