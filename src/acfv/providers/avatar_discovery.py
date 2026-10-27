from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping


MODEL_SUFFIXES = {".onnx", ".pt", ".pth", ".torchscript", ".engine", ".trt", ".pkl"}
ENTRYPOINT_NAMES = {"adapter.py", "model.py", "infer.py", "inference.py", "predict.py", "detect.py", "classifier.py"}
SIDECAR_NAMES = {"classes.json", "labels.json", "config.yaml", "config.yml", "config.json"}
PRUNED_NAMES = {".git", "__pycache__", "node_modules", "site-packages", "runs", "var", "clips"}


@dataclass(frozen=True)
class AvatarModelCandidate:
    path: str
    format: str
    framework: str
    labels: tuple[str, ...]
    inference_entry: str
    creator_coverage: tuple[str, ...]
    mtime_ns: int
    model_size: int
    sha256: str
    evidence: tuple[str, ...]
    confidence: str
    selected: bool = False
    rejection_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("labels", "creator_coverage", "evidence"):
            value[key] = list(value[key])
        return value


def _format(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    return {
        ".onnx": ("ONNX", "onnxruntime"),
        ".pt": ("PYTORCH", "pytorch/unknown"),
        ".pth": ("PYTORCH", "pytorch/unknown"),
        ".torchscript": ("TORCHSCRIPT", "pytorch"),
        ".engine": ("TENSORRT", "tensorrt"),
        ".trt": ("TENSORRT", "tensorrt"),
        ".pkl": ("PICKLE", "python/unknown"),
    }.get(suffix, ("CUSTOM", "unknown"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_labels(directory: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    evidence: list[str] = []
    for name in ("labels.json", "classes.json"):
        path = directory / name
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            values = payload.get("labels", payload.get("names", payload)) if isinstance(payload, dict) else payload
            if isinstance(values, dict):
                values = list(values.values())
            if isinstance(values, list):
                evidence.append(f"labels:{path}")
                return tuple(str(item) for item in values), tuple(evidence)
        except (OSError, UnicodeError, json.JSONDecodeError):
            evidence.append(f"unreadable-labels:{path}")
    return (), tuple(evidence)


def _entrypoint(directory: Path) -> str:
    for name in sorted(ENTRYPOINT_NAMES):
        path = directory / name
        if path.is_file():
            return str(path.resolve())
    return ""


def _configured_candidate(project_root: Path) -> tuple[Path | None, str, Path | None]:
    model = os.environ.get("ACFV_AVATAR_MODEL_PATH", "").strip()
    entrypoint = os.environ.get("ACFV_AVATAR_MODEL_ENTRYPOINT", "").strip()
    config_raw = os.environ.get("ACFV_AVATAR_MODEL_CONFIG", "").strip()
    config = Path(config_raw).expanduser().resolve() if config_raw else project_root / "config" / "avatar_identity.json"
    if config.is_file():
        try:
            payload = json.loads(config.read_text(encoding="utf-8"))
            model = model or str(payload.get("model_path", ""))
            entrypoint = entrypoint or str(payload.get("entrypoint", ""))
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    return (Path(model).expanduser().resolve() if model else None), entrypoint, (config if config.is_file() else None)


def discover_avatar_models(
    project_root: str | Path,
    *,
    search_roots: Iterable[str | Path] = (),
    label_mapping: Mapping[str, str | None] | None = None,
    max_depth: int = 5,
    max_candidates: int = 100,
) -> dict[str, Any]:
    """Bounded discovery. A filename is never sufficient evidence for selection."""
    root = Path(project_root).resolve()
    configured, configured_entrypoint, config_path = _configured_candidate(root)
    roots = [root, *(Path(item).expanduser().resolve() for item in search_roots)]
    if configured:
        roots.insert(0, configured.parent if configured.is_file() else configured)
    if label_mapping is None and config_path:
        try:
            config_payload = json.loads(config_path.read_text(encoding="utf-8"))
            config_labels = config_payload.get("labels")
            label_mapping = dict(config_labels) if isinstance(config_labels, dict) else None
        except (OSError, UnicodeError, json.JSONDecodeError):
            label_mapping = None
    mapping_provided = label_mapping is not None
    mapping = dict(label_mapping or {})
    paths: list[Path] = []
    seen: set[Path] = set()
    for search_root in roots:
        if not search_root.exists():
            continue
        if search_root.is_file():
            candidates = [search_root]
        else:
            candidates = []
            base_depth = len(search_root.parts)
            for current, directories, files in os.walk(search_root):
                current_path = Path(current)
                depth = len(current_path.parts) - base_depth
                directories[:] = [name for name in directories if name not in PRUNED_NAMES and depth < max_depth]
                candidates.extend(current_path / name for name in files if Path(name).suffix.lower() in MODEL_SUFFIXES)
                if len(candidates) >= max_candidates:
                    break
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved not in seen:
                paths.append(resolved); seen.add(resolved)
            if len(paths) >= max_candidates:
                break
        if len(paths) >= max_candidates:
            break

    audited: list[AvatarModelCandidate] = []
    selected_path = configured if configured and configured.is_file() else None
    for path in paths:
        fmt, framework = _format(path)
        labels, label_evidence = _read_labels(path.parent)
        if not labels and selected_path == path and mapping_provided:
            labels = tuple(str(label) for label in mapping)
            label_evidence = (*label_evidence, "labels:explicit-configuration")
        entrypoint = configured_entrypoint if selected_path == path and configured_entrypoint else _entrypoint(path.parent)
        coverage = tuple(sorted({value for label in labels if label in mapping if (value := mapping[label])}))
        evidence = [*label_evidence]
        if entrypoint:
            evidence.append(f"entrypoint:{entrypoint}")
        if selected_path == path:
            evidence.append("explicit-configuration")
        if config_path:
            evidence.append(f"config:{config_path}")
        # An explicit null mapping is meaningful: the detector can be selected
        # for presence inference while its label remains UNKNOWN for identity.
        selected = bool(selected_path == path and entrypoint and mapping_provided)
        rejection = ""
        confidence = "HIGH" if selected else "MEDIUM" if entrypoint and coverage else "LOW"
        if selected_path == path and not entrypoint:
            rejection = "configured model lacks an inference entrypoint"
        elif selected_path == path and not mapping_provided:
            rejection = "configured model lacks explicit label mapping"
        elif selected_path != path:
            rejection = "not explicitly configured and insufficient proof of avatar creator labels"
        stat = path.stat()
        audited.append(AvatarModelCandidate(
            path=str(path), format=fmt, framework=framework, labels=labels,
            inference_entry=entrypoint, creator_coverage=coverage, mtime_ns=stat.st_mtime_ns,
            model_size=stat.st_size, sha256=_sha256(path), evidence=tuple(evidence),
            confidence=confidence, selected=selected, rejection_reason=rejection,
        ))
    selected = next((item for item in audited if item.selected), None)
    return {
        "status": (
            "SELECTED_IDENTITY" if selected and any(mapping.values())
            else "SELECTED_PRESENCE_ONLY" if selected
            else "BLOCKED_MODEL_PATH"
        ),
        "configured_model": str(configured) if configured else "",
        "configured_entrypoint": configured_entrypoint,
        "config_path": str(config_path) if config_path else "",
        "searched_locations": [str(item) for item in roots],
        "candidates": [item.as_dict() for item in audited],
        "selected": selected.as_dict() if selected else None,
    }
