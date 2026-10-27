from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Iterable

from acfv.creator_adaptive.models import AvatarIdentityObservation


class AvatarProviderUnavailable(RuntimeError):
    pass


class AvatarIdentityProvider(ABC):
    """Provider boundary: produces observations and never writes domain state."""

    @property
    @abstractmethod
    def model_version(self) -> str: ...

    @abstractmethod
    def identify_frame(self, frame: Any, timestamp_ms: int) -> list[AvatarIdentityObservation]: ...


class ExistingAvatarModelAdapter(AvatarIdentityProvider):
    """Framework-neutral adapter for the user's existing model.

    A custom Python adapter is the safest general integration: expose either
    ``identify_frame(frame, timestamp_ms)`` or ``create_provider(path)``. ONNX and
    TorchScript formats are detected and reported, but require a sidecar Python
    adapter because class labels/preprocessing are model-specific domain knowledge.
    """

    def __init__(self, model_path: str | Path | None = None, *, entrypoint: str | Path | None = None) -> None:
        config_payload: dict[str, Any] = {}
        config_value = os.environ.get("ACFV_AVATAR_MODEL_CONFIG", "").strip()
        if config_value and Path(config_value).expanduser().is_file():
            try:
                config_payload = json.loads(Path(config_value).expanduser().read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise AvatarProviderUnavailable(f"Cannot read avatar model config: {type(exc).__name__}") from exc
        configured = str(model_path or os.environ.get("ACFV_AVATAR_MODEL_PATH", "") or config_payload.get("model_path", "")).strip()
        self.path = Path(configured).expanduser().resolve() if configured else None
        entrypoint_value = str(entrypoint or os.environ.get("ACFV_AVATAR_MODEL_ENTRYPOINT", "") or config_payload.get("entrypoint", "")).strip()
        self.entrypoint = Path(entrypoint_value).expanduser().resolve() if entrypoint_value else None
        self._callable = None
        self.format = self._detect_format(self.path)
        if self.path and self.path.exists():
            self._load()

    @staticmethod
    def _detect_format(path: Path | None) -> str:
        if path is None:
            return "NOT_CONFIGURED"
        if not path.exists():
            return "MISSING"
        if path.is_dir():
            candidates = list(path.glob("adapter.py")) + list(path.glob("*.onnx")) + list(path.glob("*.pt"))
            return ExistingAvatarModelAdapter._detect_format(candidates[0]) if candidates else "CUSTOM_DIRECTORY"
        return {
            ".py": "CUSTOM_PYTHON", ".onnx": "ONNX", ".engine": "TENSORRT",
            ".pt": "PYTORCH", ".pth": "PYTORCH", ".torchscript": "TORCHSCRIPT",
        }.get(path.suffix.lower(), "CUSTOM")

    @property
    def model_version(self) -> str:
        if not self.path or not self.path.exists():
            return self.format
        stat = self.path.stat()
        raw = f"{self.path.name}:{stat.st_size}:{stat.st_mtime_ns}"
        return f"{self.format.lower()}-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"

    @property
    def status(self) -> str:
        if self.format in {"NOT_CONFIGURED", "MISSING"}:
            return self.format
        return "READY" if self._callable else "ADAPTER_REQUIRED"

    def _load(self) -> None:
        path = self.entrypoint or self.path
        if path is None:
            return
        if path.is_dir():
            adapter = path / "adapter.py"
            if adapter.is_file():
                path = adapter
        if path.suffix.lower() != ".py":
            return
        spec = importlib.util.spec_from_file_location("acfv_user_avatar_adapter", path)
        if spec is None or spec.loader is None:
            raise AvatarProviderUnavailable(f"Cannot load avatar adapter: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        candidate = getattr(module, "identify_frame", None)
        if candidate is None and hasattr(module, "create_provider"):
            provider = module.create_provider(str(self.path))
            candidate = getattr(provider, "identify_frame", None)
        if not callable(candidate):
            raise AvatarProviderUnavailable("Custom avatar adapter must expose identify_frame")
        self._callable = candidate

    def identify_frame(self, frame: Any, timestamp_ms: int) -> list[AvatarIdentityObservation]:
        if self._callable is None:
            raise AvatarProviderUnavailable(f"Avatar provider is {self.status}; set ACFV_AVATAR_MODEL_PATH to its adapter")
        raw = self._callable(frame, int(timestamp_ms))
        if raw is None:
            return []
        observations: list[AvatarIdentityObservation] = []
        for item in raw:
            if isinstance(item, AvatarIdentityObservation):
                observations.append(item)
                continue
            if not isinstance(item, dict):
                raise TypeError("avatar observation must be a mapping")
            observations.append(AvatarIdentityObservation(
                creator_external_id=str(item.get("creator_external_id") or item.get("label") or ""),
                confidence=max(0.0, min(1.0, float(item.get("confidence", 0.0)))),
                bbox=tuple(item["bbox"]) if item.get("bbox") else None,
                track_id=str(item["track_id"]) if item.get("track_id") is not None else None,
                timestamp_ms=int(item.get("timestamp_ms", timestamp_ms)),
                model_version=str(item.get("model_version") or self.model_version),
                provider=str(item.get("provider") or "existing-avatar-model"),
                frame_quality=max(0.0, min(1.0, float(item.get("frame_quality", 1.0)))),
                raw_metadata=dict(item.get("raw_metadata") or {}),
            ))
        return observations

    def audit(self) -> dict[str, Any]:
        return {
            "configured_path": str(self.path) if self.path else "",
            "entrypoint": str(self.entrypoint) if self.entrypoint else "",
            "format": self.format,
            "status": self.status,
            "model_version": self.model_version,
            "contract": "identify_frame(frame,timestamp_ms)->List[AvatarIdentityObservation]",
        }


def write_adapter_template(path: Path) -> Path:
    payload = {
        "contract": "identify_frame(frame, timestamp_ms)",
        "required_output": ["creator_external_id", "confidence"],
        "optional_output": ["bbox", "track_id", "timestamp_ms", "model_version", "provider", "frame_quality", "raw_metadata"],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path

