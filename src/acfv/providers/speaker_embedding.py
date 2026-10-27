from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Sequence


class SpeakerProviderUnavailable(RuntimeError):
    pass


class SpeakerEmbeddingProvider(ABC):
    """WHO-only provider. Embeddings are forbidden as lexical evidence."""

    lexical_evidence_supported = False

    @property
    @abstractmethod
    def model_version(self) -> str: ...

    @abstractmethod
    def embed(self, audio_path: str | Path, *, start_ms: int = 0, end_ms: int | None = None) -> Sequence[float]: ...


class ResemblyzerSpeakerEmbeddingProvider(SpeakerEmbeddingProvider):
    """Optional Apache-2.0 resemblyzer provider already declared by ACFV."""

    license = "Apache-2.0"

    def __init__(self, *, device: str = "cpu") -> None:
        self.device = device
        self._encoder = None

    @property
    def model_version(self) -> str:
        return "resemblyzer-voice-encoder"

    def _load(self):
        if self._encoder is None:
            try:
                from resemblyzer import VoiceEncoder
            except ImportError as exc:
                raise SpeakerProviderUnavailable("resemblyzer is not installed") from exc
            self._encoder = VoiceEncoder(device=self.device)
        return self._encoder

    def embed(self, audio_path: str | Path, *, start_ms: int = 0, end_ms: int | None = None) -> Sequence[float]:
        try:
            import librosa
        except ImportError as exc:
            raise SpeakerProviderUnavailable("librosa is not installed") from exc
        duration = None if end_ms is None else max(0.0, (end_ms - start_ms) / 1000)
        wav, _ = librosa.load(str(audio_path), sr=16000, mono=True, offset=max(0, start_ms) / 1000, duration=duration)
        if len(wav) < 1600:
            raise ValueError("speaker embedding requires at least 100 ms of audio")
        return self._load().embed_utterance(wav).astype(float).tolist()


class SpeechBrainECAPASpeakerEmbeddingProvider(SpeakerEmbeddingProvider):
    """Optional SpeechBrain ECAPA-TDNN WHO-only comparison provider."""

    license = "Apache-2.0"

    def __init__(
        self,
        *,
        device: str = "cpu",
        model_source: str = "speechbrain/spkrec-ecapa-voxceleb",
        cache_dir: str | Path | None = None,
    ) -> None:
        self.device = device
        self.model_source = model_source
        self.cache_dir = Path(cache_dir).expanduser().resolve() if cache_dir else None
        self._classifier = None

    @property
    def model_version(self) -> str:
        return f"speechbrain-ecapa:{self.model_source}"

    def _load(self):
        if self._classifier is None:
            try:
                from speechbrain.inference.speaker import EncoderClassifier
                from speechbrain.utils.fetching import LocalStrategy
            except ImportError as exc:
                raise SpeakerProviderUnavailable("speechbrain is not installed") from exc
            kwargs = {
                "source": self.model_source,
                "run_opts": {"device": self.device},
                # SpeechBrain defaults to symlinks, which require elevated
                # privileges on many Windows installations.  A local copy is
                # deterministic and works for ordinary desktop users.
                "local_strategy": LocalStrategy.COPY,
            }
            if self.cache_dir is not None:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                kwargs["savedir"] = str(self.cache_dir)
            self._classifier = EncoderClassifier.from_hparams(**kwargs)
        return self._classifier

    def embed(self, audio_path: str | Path, *, start_ms: int = 0, end_ms: int | None = None) -> Sequence[float]:
        try:
            import torch
            import torchaudio
        except ImportError as exc:
            raise SpeakerProviderUnavailable("torch and torchaudio are required for ECAPA") from exc
        signal, sample_rate = torchaudio.load(str(audio_path))
        if signal.ndim == 2:
            signal = signal.mean(dim=0, keepdim=True)
        left = max(0, int(start_ms * sample_rate / 1000))
        right = signal.shape[-1] if end_ms is None else min(signal.shape[-1], int(end_ms * sample_rate / 1000))
        signal = signal[:, left:right]
        if signal.shape[-1] < max(1600, int(sample_rate * .1)):
            raise ValueError("speaker embedding requires at least 100 ms of audio")
        if sample_rate != 16000:
            signal = torchaudio.functional.resample(signal, sample_rate, 16000)
        with torch.inference_mode():
            embedding = self._load().encode_batch(signal.to(self.device)).squeeze()
        return embedding.detach().float().cpu().numpy().astype(float).tolist()

