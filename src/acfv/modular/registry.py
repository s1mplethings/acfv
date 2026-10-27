from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from .types import AdapterSpec, ArtifactType, ModuleSpec


class ModuleRegistry:
    def __init__(self) -> None:
        self._modules: Dict[str, ModuleSpec] = {}

    def register(self, spec: ModuleSpec) -> None:
        self._modules[spec.name] = spec

    def register_many(self, specs: Iterable[ModuleSpec]) -> None:
        for spec in specs:
            self.register(spec)

    def get(self, name: str) -> Optional[ModuleSpec]:
        return self._modules.get(name)

    def list(self) -> List[ModuleSpec]:
        return list(self._modules.values())

    def by_output(self, artifact_type: ArtifactType) -> List[ModuleSpec]:
        return [spec for spec in self._modules.values() if artifact_type in spec.outputs]


class AdapterRegistry:
    def __init__(self) -> None:
        self._by_target: Dict[ArtifactType, List[AdapterSpec]] = {}

    def register(self, spec: AdapterSpec) -> None:
        self._by_target.setdefault(spec.target_type, []).append(spec)

    def register_many(self, specs: Iterable[AdapterSpec]) -> None:
        for spec in specs:
            self.register(spec)

    def find_adapter(self, target_type: ArtifactType, available: Iterable[ArtifactType]) -> Optional[AdapterSpec]:
        for spec in self._by_target.get(target_type, []):
            if spec.source_type in available:
                return spec
        return None


__all__ = ["ModuleRegistry", "AdapterRegistry"]
