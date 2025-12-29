from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

ArtifactType = str
ProgressCallback = Callable[[str, int, int, str], None]


@dataclass
class ArtifactEnvelope:
    artifact_id: str
    type: ArtifactType
    schema_version: str = "1"
    timebase: str = "seconds"
    time_range: Optional[List[float]] = None
    producer: Dict[str, Any] = field(default_factory=dict)
    payload: Any = None
    payload_ref: Optional[str] = None
    fingerprint: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)


if TYPE_CHECKING:
    from .store import ArtifactStore


@dataclass
class ModuleContext:
    inputs: Dict[ArtifactType, ArtifactEnvelope]
    params: Dict[str, Any]
    store: "ArtifactStore"
    run_id: str
    progress: Optional[ProgressCallback] = None


@dataclass
class AdapterContext:
    source: ArtifactEnvelope
    params: Dict[str, Any]
    store: "ArtifactStore"
    run_id: str
    progress: Optional[ProgressCallback] = None


ModuleRun = Callable[[ModuleContext], Dict[ArtifactType, Any]]
AdapterRun = Callable[[AdapterContext], Any]


@dataclass
class ModuleSpec:
    name: str
    version: str
    inputs: List[ArtifactType]
    outputs: List[ArtifactType]
    run: ModuleRun
    description: str = ""
    impl_path: Optional[str] = None
    default_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AdapterSpec:
    name: str
    version: str
    source_type: ArtifactType
    target_type: ArtifactType
    run: AdapterRun
    description: str = ""


@dataclass
class PlanStep:
    module: ModuleSpec


__all__ = [
    "ArtifactType",
    "ProgressCallback",
    "ArtifactEnvelope",
    "ModuleContext",
    "AdapterContext",
    "ModuleSpec",
    "AdapterSpec",
    "PlanStep",
]
