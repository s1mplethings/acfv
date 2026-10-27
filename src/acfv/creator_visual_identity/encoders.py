from __future__ import annotations

import hashlib
from pathlib import Path
import time
from typing import Any, Iterable

import cv2
import numpy as np
from PIL import Image


def _pil(image: Any) -> Image.Image:
    if isinstance(image, Image.Image):
        return image.convert("RGB")
    array = np.asarray(image)
    if array.ndim != 3 or array.shape[2] not in (3, 4):
        raise ValueError("visual encoder expects an HxWx3/4 image")
    if array.shape[2] == 4:
        array = cv2.cvtColor(array, cv2.COLOR_BGRA2RGB)
    else:
        array = cv2.cvtColor(array, cv2.COLOR_BGR2RGB)
    return Image.fromarray(array)


class TransformersVisionEncoder:
    def __init__(self, model_name: str, *, kind: str, device: str = "cuda", local_files_only: bool = False) -> None:
        import torch
        from transformers import AutoImageProcessor, AutoModel, CLIPImageProcessor, CLIPVisionModelWithProjection

        self.kind = kind
        self.model_name = model_name
        self.device = torch.device(device if device != "cuda" or torch.cuda.is_available() else "cpu")
        if kind == "dinov2":
            self.processor = AutoImageProcessor.from_pretrained(model_name, local_files_only=local_files_only)
            self.model = AutoModel.from_pretrained(model_name, local_files_only=local_files_only)
        elif kind == "openclip":
            self.processor = CLIPImageProcessor.from_pretrained(model_name, local_files_only=local_files_only)
            self.model = CLIPVisionModelWithProjection.from_pretrained(model_name, local_files_only=local_files_only)
        else:
            raise ValueError(f"unsupported encoder kind: {kind}")
        self.model.eval().to(self.device)
        revision = getattr(self.model.config, "_commit_hash", None) or "unknown"
        self._model_version = f"{kind}:{model_name}:{revision}"

    @property
    def model_version(self) -> str:
        return self._model_version

    def encode(self, images: Iterable[Any], *, batch_size: int = 32) -> np.ndarray:
        import torch
        rows = list(images)
        outputs: list[np.ndarray] = []
        with torch.inference_mode():
            for offset in range(0, len(rows), batch_size):
                batch = [_pil(image) for image in rows[offset:offset + batch_size]]
                inputs = self.processor(images=batch, return_tensors="pt")
                inputs = {key: value.to(self.device) for key, value in inputs.items()}
                result = self.model(**inputs)
                if self.kind == "openclip":
                    vectors = result.image_embeds
                else:
                    vectors = result.last_hidden_state[:, 0]
                vectors = torch.nn.functional.normalize(vectors.float(), dim=1)
                outputs.append(vectors.cpu().numpy())
        return np.concatenate(outputs, axis=0) if outputs else np.empty((0, 0), dtype=np.float32)


class TorchvisionEncoder:
    def __init__(self, *, architecture: str = "resnet18", weights_path: Path | None = None, device: str = "cuda") -> None:
        import torch
        from torchvision.models import resnet18

        if architecture != "resnet18":
            raise ValueError("only resnet18 is supported by the lightweight baseline")
        self.device = torch.device(device if device != "cuda" or torch.cuda.is_available() else "cpu")
        model = resnet18(weights=None)
        if weights_path:
            state = torch.load(str(weights_path), map_location="cpu", weights_only=True)
            model.load_state_dict(state)
            weight_hash = hashlib.sha256(Path(weights_path).read_bytes()).hexdigest()[:12]
        else:
            weight_hash = "random"
        self.feature_dim = model.fc.in_features
        model.fc = torch.nn.Identity()
        self.model = model.eval().to(self.device)
        self._model_version = f"torchvision:resnet18:{weight_hash}"

    @property
    def model_version(self) -> str:
        return self._model_version

    def encode(self, images: Iterable[Any], *, batch_size: int = 64) -> np.ndarray:
        import torch
        from torchvision.transforms import v2

        transform = v2.Compose([
            v2.ToImage(), v2.Resize((224, 224), antialias=True), v2.ToDtype(torch.float32, scale=True),
            v2.Normalize(mean=(.485, .456, .406), std=(.229, .224, .225)),
        ])
        rows = list(images)
        outputs: list[np.ndarray] = []
        with torch.inference_mode():
            for offset in range(0, len(rows), batch_size):
                tensors = [transform(np.asarray(_pil(image))) for image in rows[offset:offset + batch_size]]
                batch = torch.stack(tensors).to(self.device)
                vectors = torch.nn.functional.normalize(self.model(batch).float(), dim=1)
                outputs.append(vectors.cpu().numpy())
        return np.concatenate(outputs, axis=0) if outputs else np.empty((0, self.feature_dim), dtype=np.float32)


class TimmVisionEncoder:
    """Frozen timm feature extractor used by the lightweight identity benchmark."""

    def __init__(self, model_name: str, *, device: str = "cuda", pretrained: bool = True) -> None:
        import timm
        import torch

        self.model_name = model_name
        self.device = torch.device(device if device != "cuda" or torch.cuda.is_available() else "cpu")
        self.model = timm.create_model(model_name, pretrained=pretrained, num_classes=0).eval().to(self.device)
        self.data_config = timm.data.resolve_model_data_config(self.model)
        self.transform = timm.data.create_transform(**self.data_config, is_training=False)
        cfg = dict(getattr(self.model, "pretrained_cfg", {}) or {})
        source = str(cfg.get("hf_hub_id") or cfg.get("url") or "random")
        self.feature_dim = int(getattr(self.model, "num_features", 0) or 0)
        self._model_version = f"timm:{model_name}:{source}"

    @property
    def model_version(self) -> str:
        return self._model_version

    def encode(self, images: Iterable[Any], *, batch_size: int = 32) -> np.ndarray:
        import torch

        rows = list(images)
        outputs: list[np.ndarray] = []
        with torch.inference_mode():
            for offset in range(0, len(rows), batch_size):
                batch = torch.stack([self.transform(_pil(image)) for image in rows[offset:offset + batch_size]]).to(self.device)
                vectors = torch.nn.functional.normalize(self.model(batch).float(), dim=1)
                outputs.append(vectors.cpu().numpy())
        return np.concatenate(outputs, axis=0) if outputs else np.empty((0, self.feature_dim), dtype=np.float32)


class OpenClipVisionEncoder:
    """Frozen OpenCLIP image encoder (distinct from Transformers CLIP)."""

    def __init__(self, model_name: str = "ViT-B-32-quickgelu", *, pretrained: str = "openai", device: str = "cuda") -> None:
        import open_clip
        import torch

        self.device = torch.device(device if device != "cuda" or torch.cuda.is_available() else "cpu")
        self.model, _, self.transform = open_clip.create_model_and_transforms(model_name, pretrained=pretrained)
        self.model = self.model.eval().to(self.device)
        self.feature_dim = int(getattr(self.model.visual, "output_dim", 0) or 0)
        self._model_version = f"open_clip:{open_clip.__version__}:{model_name}:{pretrained}"

    @property
    def model_version(self) -> str:
        return self._model_version

    def encode(self, images: Iterable[Any], *, batch_size: int = 32) -> np.ndarray:
        import torch

        rows = list(images)
        outputs: list[np.ndarray] = []
        with torch.inference_mode():
            for offset in range(0, len(rows), batch_size):
                batch = torch.stack([self.transform(_pil(image)) for image in rows[offset:offset + batch_size]]).to(self.device)
                vectors = torch.nn.functional.normalize(self.model.encode_image(batch).float(), dim=1)
                outputs.append(vectors.cpu().numpy())
        return np.concatenate(outputs, axis=0) if outputs else np.empty((0, self.feature_dim), dtype=np.float32)


def timed_encode(encoder: Any, images: Iterable[Any], *, batch_size: int = 32) -> tuple[np.ndarray, dict[str, float]]:
    import psutil
    import torch

    rows = list(images)
    process = psutil.Process()
    ram_before = process.memory_info().rss
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    vectors = encoder.encode(rows, batch_size=batch_size)
    elapsed = time.perf_counter() - started
    return vectors, {
        "frames": len(rows), "elapsed_s": elapsed, "fps": len(rows) / elapsed if elapsed else 0.0,
        "latency_ms_per_frame": elapsed * 1000 / len(rows) if rows else 0.0,
        "ram_delta_mb": (process.memory_info().rss - ram_before) / 1048576,
        "gpu_peak_mb": torch.cuda.max_memory_allocated() / 1048576 if torch.cuda.is_available() else 0.0,
    }
