from __future__ import annotations

from typing import Iterable, List, Sequence, Set

from .registry import ModuleRegistry
from .types import ArtifactType, ModuleSpec, PlanStep


class PlanError(RuntimeError):
    pass


def build_plan(
    goal_types: Sequence[ArtifactType],
    module_registry: ModuleRegistry,
    available_types: Iterable[ArtifactType],
) -> List[PlanStep]:
    available: Set[ArtifactType] = set(available_types)
    remaining: Set[ArtifactType] = set(goal_types)
    pending = list(module_registry.list())
    steps: List[PlanStep] = []

    while remaining:
        progressed = False
        for spec in list(pending):
            if set(spec.inputs).issubset(available):
                new_outputs = set(spec.outputs) - available
                if not new_outputs:
                    pending.remove(spec)
                    continue
                steps.append(PlanStep(module=spec))
                available.update(spec.outputs)
                remaining -= set(spec.outputs)
                pending.remove(spec)
                progressed = True
        if not progressed:
            break

    if remaining:
        raise PlanError(
            "Unreachable goals. Missing types: "
            + ", ".join(sorted(remaining))
            + ". Available types: "
            + ", ".join(sorted(available))
        )

    return steps


__all__ = ["PlanError", "build_plan"]
