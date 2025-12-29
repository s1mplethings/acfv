from __future__ import annotations

from acfv.modular.types import ModuleSpec

from .step import IN_TYPE, OUT_TYPE, run


spec = ModuleSpec(
    name="merge_segments",
    version="0.1",
    inputs=[IN_TYPE],
    outputs=[OUT_TYPE],
    run=run,
    description="Normalize and filter segment candidates into unified schema.",
    impl_path="src/acfv/steps/merge_segments/step.py",
    default_params={"min_score": 0.0},
)

__all__ = ["spec"]
