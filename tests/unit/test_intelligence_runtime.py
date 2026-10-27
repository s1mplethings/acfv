from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from acfv.library import LibraryService
from acfv.moments import MomentService
from acfv.ragstack.embeddings import encoder as encoder_module
from acfv.ragstack.embeddings.encoder import DeterministicHashEncoder, EmbeddingModelUnavailable, TransformersEmbeddingEncoder
from acfv.retrieval import PersistentMomentIndex
from acfv.retrieval import reranker as reranker_module


def test_production_embedding_failure_never_silently_hashes(monkeypatch) -> None:
    monkeypatch.delenv("ACFV_TEST_DETERMINISTIC_EMBEDDING", raising=False)
    monkeypatch.setattr(encoder_module, "_load_real_encoder", lambda *_args: (_ for _ in ()).throw(EmbeddingModelUnavailable("missing")))
    with pytest.raises(EmbeddingModelUnavailable, match="missing"):
        encoder_module.load_encoder("missing/model")


def test_hash_embedding_requires_explicit_test_mode(monkeypatch) -> None:
    monkeypatch.setenv("ACFV_TEST_DETERMINISTIC_EMBEDDING", "1")
    encoder = encoder_module.load_encoder("test/model")
    assert isinstance(encoder, DeterministicHashEncoder)
    assert encoder(["same"]).shape == (1, 384)


def test_index_rejects_embedding_model_mismatch(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Creator")
    recording = library.register_recording(creator_id=creator.id, title="Stream", require_file=False)
    MomentService(library.repository).ingest_incremental(recording.id, {"segments": [{"start": 0, "end": 5, "text": "meaningful event"}]})
    injected = lambda texts: np.ones((len(list(texts)), 8), dtype=np.float32)
    root = tmp_path / "index"
    PersistentMomentIndex(library.repository, root, encoder=injected, model_name="model/a").rebuild()
    incompatible = PersistentMomentIndex(library.repository, root, encoder=injected, model_name="model/b")
    with pytest.raises(RuntimeError, match="model changed"):
        incompatible.rows()


def test_reranker_unavailable_is_explicit(monkeypatch) -> None:
    monkeypatch.setenv("ACFV_RERANKER_ENABLED", "1")
    monkeypatch.setattr(reranker_module, "load_cross_encoder", lambda *_args: None)
    assert reranker_module.local_cross_encoder("missing/model") is None


def test_reranker_can_be_explicitly_disabled(monkeypatch) -> None:
    monkeypatch.setenv("ACFV_RERANKER_ENABLED", "0")
    assert reranker_module.local_cross_encoder("any/model") is None


def test_e5_query_and_passage_prefixes_are_applied_without_mutating_text() -> None:
    encoder = object.__new__(TransformersEmbeddingEncoder)
    captured = []
    encoder._encode = lambda texts: captured.append(texts) or np.ones((len(texts), 2), dtype=np.float32)
    encoder.encode_queries(["  中文 query  "])
    encoder.encode_passages(["  English passage  "])
    assert captured == [["query: 中文 query"], ["passage: English passage"]]


def test_e5_outputs_are_l2_normalized() -> None:
    encoder = DeterministicHashEncoder()
    vectors = encoder.encode_queries(["中文问题", "English question", "日本語の質問"])
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


def test_transformer_encoder_materializes_weights_without_meta_device(monkeypatch) -> None:
    calls = {}

    class Model:
        config = SimpleNamespace(hidden_size=8)

        def to(self, device):
            calls["device"] = device
            return self

        def eval(self):
            calls["eval"] = True

    fake_transformers = SimpleNamespace(
        AutoTokenizer=SimpleNamespace(from_pretrained=lambda name: ("tokenizer", name)),
        AutoModel=SimpleNamespace(
            from_pretrained=lambda name, **kwargs: calls.update(name=name, kwargs=kwargs) or Model()
        ),
    )
    monkeypatch.setitem(__import__("sys").modules, "torch", SimpleNamespace())
    monkeypatch.setitem(__import__("sys").modules, "transformers", fake_transformers)

    encoder = TransformersEmbeddingEncoder("model/name", device="cpu")

    assert calls["kwargs"] == {"low_cpu_mem_usage": False}
    assert calls["device"] == "cpu"
    assert calls["eval"] is True
    assert encoder.dimension == 8
